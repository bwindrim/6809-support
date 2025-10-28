import rp2
import time
from machine import Pin
import uasyncio as asyncio

LED = Pin(25, Pin.OUT)

#TXD = Pin(0, Pin.OUT)
#RXD = Pin(1, Pin.IN)
PB0 = Pin(2, Pin.IN)
PB1 = Pin(3, Pin.IN)
PB2 = Pin(4, Pin.IN)
PB3 = Pin(5, Pin.IN)
PB4 = Pin(6, Pin.IN)
PB5 = Pin(7, Pin.IN)
PB6 = Pin(8, Pin.IN)
PB7 = Pin(9, Pin.IN)
CB2 = Pin(10, Pin.IN)
CA2 = Pin(11, Pin.IN)
PA0 = Pin(12, Pin.OUT)
PA1 = Pin(13, Pin.OUT)
PA2 = Pin(14, Pin.OUT)
PA3 = Pin(15, Pin.OUT)
PA4 = Pin(16, Pin.OUT)
PA5 = Pin(17, Pin.OUT)
PA6 = Pin(18, Pin.OUT)
PA7 = Pin(19, Pin.OUT)
CA1 = Pin(20, Pin.OUT, value=1) # set port A "data ready" output high
CB1 = Pin(21, Pin.OUT, value=1) # set port B "data taken" output high
NMI = Pin(22, Pin.OUT, value=0) # set NMI low (inactive)
RST = Pin(26, Pin.OUT, value=1) # note: this takes the 6809 out of reset when set low

PORTA = [PA7, PA6, PA5, PA4, PA3, PA2, PA1, PA0]
PortA_DATA_READY = CA1
PortA_DATA_TAKEN = CA2

PORTB = [PB7, PB6, PB5, PB4, PB3, PB2, PB1, PB0]
PortB_DATA_TAKEN = CB1
PortB_DATA_READY = CB2 


@rp2.asm_pio()
def count_strobes():
    label('count_strobes')
    wait(0, pin, 0)     # wait for rising edge
    irq(rel(0))         # trigger an IRQ to Python
    jmp('count_strobes')

# Set up PIO
#sm = rp2.StateMachine(0, count_strobes, freq=2000_000, in_base=PortA_DATA_TAKEN)
#sm.irq(lambda p: print("Strobe detected"))
#sm.active(1)
#time.sleep(0.1)  # give PIO time to start

def dload_exec(load_addr, data, exec_addr):
    "Download bytes and execute specified address - not necessarily within the download"
 
    send_bytes(b'\xAA')      # send the download prefix byte
    send_word(load_addr)     # send the destination addess
    send_word(len(data))     # send the data length
    send_bytes(data)         # send the data
    send_word(exec_addr)     # send the execution address

def bus_read(port):
    "Read the 8 bits of the specified port into a list of bits"
    bits = 0
    for pin in port:
        bits = (bits << 1) | pin.value()
    return bits

# Send bytes with a pulse on CA1 to indicate data ready.
# This does not wait for acknowledgement from the 6809, but has a 1ms delay
# after sending each byte.
# This function is used for bootloading only, to send the second-stage bootloader
# to the first-stage bootloader.
def send_bytes_pulse(out_bytes):
    "write a series of bytes to Port A, with handshaking"
    
    for int8 in out_bytes:
        assert int8 < 256
        output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
        for pin, val in zip(PORTA, output):
            pin.value(val)
        PortA_DATA_READY.low()   # signal data ready
        time.sleep_ms(1)  # wait 1ms for data taken (should be much less)

        # Assume the data has been taken.
        PortA_DATA_READY.high()  # clear data ready

# Send bytes with handshake on CA1/CA2.
# This waits for the 6809 to acknowledge each byte before sending the next.
# This function is used for general data transfer after bootloading.
def send_bytes_handshake(out_bytes):
    "write a series of bytes to Port A, with handshaking"
    
    for int8 in out_bytes:
        assert int8 < 256
        output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
        for pin, val in zip(PORTA, output):
            pin.value(val)
        PortA_DATA_READY.low()   # signal data ready
        # Wait for the 6809 to signal data taken.
        while PortA_DATA_TAKEN() != 0:
            pass
        PortA_DATA_READY.high()  # clear data ready

send_bytes = send_bytes_pulse

def send_word(word):
    "Helper function to send a 16-bit integer, in hi-lo order"
    send_bytes(word.to_bytes(2, 'big'))

def dload_exec_file(filename):
    "Download and execute the specified file"
    with open (filename, 'rb') as f:
        # Get load address
        load_addr = int.from_bytes(f.read(2), "big")
        # Get data length
        length = int.from_bytes(f.read(2), "big")
        # Get data
        data = f.read(length)
        assert length == len(data)
        # Get exec address
        exec_addr = int.from_bytes(f.read(2), "big")

        print ("load address = ", hex(load_addr),
               "length = ", length,
               "exec address = ", hex(exec_addr));
        
        dload_exec(load_addr, data, exec_addr)

async def get_bytes():
    "read a (non-empty) sequence of bytes from the 6809. Non-blocking coroutine."
    in_bytes = bytearray()

    # Wait until 6809 asserts data-ready (active low)
    while PortB_DATA_READY.value() != 0:
        await asyncio.sleep_ms(1)

    # Read at least one byte (to guarantee non-empty result) and keep
    # reading bytes while data-ready remains asserted.
    while True:
        int8 = bus_read(PORTB)
        PortB_DATA_TAKEN.low()
        in_bytes.append(int8)
        PortB_DATA_TAKEN.high()
        await asyncio.sleep_ms(0)  # yield
        if PortB_DATA_READY.value() != 0:
            break
    return in_bytes

async def toggle_nmi():
    "Toggle NMI every 3 seconds"
    while True:
        await asyncio.sleep_ms(3000)
        NMI.toggle()

async def listen():
    "Wait for bytes from the 6809 and output them to the console (async task)"

    asyncio.create_task(toggle_nmi())

    while True:
        in_bytes = await get_bytes()
        print(in_bytes)

# Main program starts here
try:
    LED.on()
    time.sleep_ms(250)  # wait 250ms for 6809 to reset
    RST.low()
    time.sleep_ms(250)  # wait 250ms for 6809 to start up
    dload_exec_file("boot2.ex9")
    send_bytes = send_bytes_handshake
    dload_exec_file("blink1.ex9")
    for pin in PORTA:
        pin.init(Pin.IN)  # release Port A pins
    print("Download complete, listening...")
    # Run the async listener (this will block here until cancelled)
    asyncio.run(listen())
except KeyboardInterrupt:
    print("Interrupted by user")
finally:
    for pin in PORTA:
        pin.init(Pin.IN)  # release Port A pins
    print("Done.")
    LED.off()
