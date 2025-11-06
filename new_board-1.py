import rp2
import time
from machine import Pin
import uasyncio as asyncio

#TXD = Pin(0, Pin.OUT)
#RXD = Pin(1, Pin.IN)
#PB0 = Pin(2, Pin.IN)
#PB1 = Pin(3, Pin.IN)
#PB2 = Pin(4, Pin.IN)
#PB3 = Pin(5, Pin.IN)
#PB4 = Pin(6, Pin.IN)
#PB5 = Pin(7, Pin.IN)
#PB6 = Pin(8, Pin.IN)
#PB7 = Pin(9, Pin.IN)
#CB2 = Pin(10, Pin.IN)
CA2 = Pin(11, Pin.IN)
PA0 = Pin(12, Pin.IN)
PA1 = Pin(13, Pin.IN)
PA2 = Pin(14, Pin.IN)
PA3 = Pin(15, Pin.IN)
PA4 = Pin(16, Pin.IN)
PA5 = Pin(17, Pin.IN)
PA6 = Pin(18, Pin.IN)
PA7 = Pin(19, Pin.IN)
CA1 = Pin(20, Pin.OUT, value=1) # set port A "data ready" output high
#CB1 = Pin(21, Pin.OUT, value=1) # set port B "data taken" output high
NMI = Pin(22, Pin.OUT, value=0) # set NMI low (inactive)
LED = Pin(25, Pin.OUT)
RST = Pin(26, Pin.OUT, value=1) # holds the 6809 in reset until set low, below

PORTA = [PA7, PA6, PA5, PA4, PA3, PA2, PA1, PA0]


@rp2.asm_pio()
def count_strobes():
    label('count_strobes')
    wait(0, pin, 0)     # wait for rising edge
    irq(rel(0))         # trigger an IRQ to Python
    jmp('count_strobes')

# Set up PIO
#sm = rp2.StateMachine(0, count_strobes, freq=2000_000, in_base=CA2)
#sm.irq(lambda p: print("Strobe detected"))
#sm.active(1)
#time.sleep(0.1)  # give PIO time to start

def dload_exec(load_addr, data, exec_addr):
    "Download bytes and execute specified address - not necessarily within the download"
    try:
        for pin in PORTA:
            pin.init(Pin.OUT)    # set Port A pins to output
        send_bytes(b'\xAA')      # send the download prefix byte
        send_word(load_addr)     # send the destination addess
        send_word(len(data))     # send the data length
        send_bytes(data)         # send the data
        send_word(exec_addr)     # send the execution address
    except Exception as e:
        print("Error during download/exec:", e)
    finally:
        for pin in PORTA:
            pin.init(Pin.IN)  # release Port A pins

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
        CA1.low()   # signal data ready
        time.sleep_ms(1)  # wait 1ms for data taken (should be much less)

        # Assume the data has been taken.
        CA1.high()  # clear data ready

# Send bytes with handshake on CA1/CA2.
# This waits for the 6809 to acknowledge each byte before sending the next.
# This function is used for general data transfer after bootloading.
def send_bytes_handshake(out_bytes, port=PORTA, data_ready=CA1, data_taken=CA2):
    "write a series of bytes to the specified port, with handshaking"

    for int8 in out_bytes:
        assert int8 < 256
        output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
        for pin, val in zip(port, output):
            pin.value(val)
        data_ready.low()   # signal data ready
        # Wait for the 6809 to signal data taken.
        while data_taken() != 0:
            pass
        data_ready.high()  # clear data ready

# Initially, use the pulse version for bootloading.
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

        print (filename, "load address = ", hex(load_addr),
               "length = ", length,
               "exec address = ", hex(exec_addr));
        
        dload_exec(load_addr, data, exec_addr)

async def get_bytes(port=PORTA, data_ready=CA2, data_taken=CA1):
    "read a (non-empty) sequence of bytes from the 6809. Non-blocking coroutine."
    in_bytes = bytearray()

    # Wait until 6809 asserts data-ready (active low)
    while data_ready.value() != 0:
        await asyncio.sleep_ms(1)

    # Read at least one byte (to guarantee non-empty result) and keep
    # reading bytes while data_ready remains asserted (low).
    while True:
        int8 = bus_read(port)
        data_taken.low()
        in_bytes.append(int8)
        data_taken.high()
        await asyncio.sleep_ms(0)  # yield
        if data_ready.value() != 0:
            break
    return in_bytes

async def toggle_nmi():
    "Toggle NMI every 3 seconds (async task)"
    while True:
        await asyncio.sleep_ms(3000)
        NMI.toggle()

async def listen():
    "Wait for bytes from the 6809 and output them to the console (async task)"

    asyncio.create_task(toggle_nmi())

    while True:
        in_bytes = await get_bytes()
        LED.toggle()
        try:
            # Print the incoming bytes as UTF-8, if valid...
            print(in_bytes.decode('utf-8'), end='')
        except UnicodeError:
            # ...otherwise, just print the raw bytes.
            print(in_bytes)
        await asyncio.sleep_ms(10)  # yield
        LED.toggle()

# Main program starts here
try:
    LED.on()
    time.sleep_ms(250)  # wait 250ms for 6809 to reset
    RST.low() # take 6809 out of reset
    time.sleep_ms(250)  # wait 250ms for 6809 to start up
    dload_exec_file("boot2.ex9") # load second-stage bootloader
    send_bytes = send_bytes_handshake # switch to handshake version after bootloading
    dload_exec_file("despatch.ex9") # load the 6522 interrupt despatcher
    dload_exec_file("blink3.ex9") # load the target program
    print("Download complete, listening...")
    # Run the async listener (this will block here until cancelled)
    asyncio.run(listen())
except KeyboardInterrupt:
    print("Interrupted by user")
finally:
    print("Done.")
    LED.off()
