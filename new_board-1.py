import rp2
import time
from machine import Pin

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
CA1 = Pin(20, Pin.OUT)
CB1 = Pin(21, Pin.OUT)
NMI = Pin(22, Pin.OUT)
RST = Pin(26, Pin.OUT) # note: this gets set low when initialised as output, which takes the 6809 out of reset

PORTA = [PA7, PA6, PA5, PA4, PA3, PA2, PA1, PA0]
PortA_DATA_READY = CA1
PortA_DATA_TAKEN = CA2

PORTB = [PB7, PB6, PB5, PB4, PB3, PB2, PB1, PB0]
PortB_DATA_TAKEN = CB1
PortB_DATA_READY = CB2 

PortA_DATA_READY.value(1)  # set "data ready" output high
PortB_DATA_TAKEN.value(1)  # set "data taken" output high


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
    
def bus_read_int8():
    "Read the 8 bits of the data bus into an integer"
    B0 = PB0.value()
    B1 = PB1.value()
    B2 = PB2.value()
    B3 = PB3.value()
    B4 = PB4.value()
    B5 = PB5.value()
    B6 = PB6.value()
    B7 = PB7.value()

    return (B0 |
            B1 << 1 |
            B2 << 2 |
            B3 << 3 |
            B4 << 4 |
            B5 << 5 |
            B6 << 6 |
            B7 << 7
        )

def bus_read():
    "Read the 8 bits of the data bus into a list"
    int8 = bus_read_int8()
    return [int(x) for x in '{:08b}'.format(int8)]

def send_bytes(out_bytes):
    "write a series of bytes to Port A, with handshake, and read back from port B"
    validate = False
    
    for int8 in out_bytes:
        assert int8 < 256
        output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
        for pin, val in zip(PORTA, output):
            pin.value(val)
        PortA_DATA_READY.value(0)   # signal data ready
        # Wait for the 6809 to signal data taken.
        #while PortA_DATA_TAKEN.value() == 1:
        #    pass
        time.sleep_ms(1)  # wait 1ms for data taken (should be much less)

        # Data taken, we can now change the bus
        PortA_DATA_READY.value(1)  # clear data ready

        # Optional readback validation of sent byte
        if validate:
            while PortB_DATA_READY.value() == 0:
                pass
            
            # read back
            # setup for input from port B
            
            # read data from bus, compare output and input
            input = bus_read()
            if input != output:
                print("output = ", output, "input = ", input)
                
            # Note that we don't signal "data taken" during download validation,
            # as the 6809 is in strobe mode and isn't looking for it. Also,
            # signalling data taken was causing us to miss the first byte sent
            # by the downloaded program.

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

def get_bytes():
    "read a (possibly empty) sequence of bytes from the 6809. Non-blocking."
    in_bytes = bytearray() # return value, possibly empty

    # Check for data ready on port B (active low). This depends on us detecting the data ready
    # pulse during the 500ns that it is low.
    while 0 == PortB_DATA_READY.value():
        # Data ready, so read the bus and append to in_bytes.
        int8 = bus_read_int8()
        # Pulse PortB_DATA_TAKEN (CB1) active low.
        # Note that PortB_DATA_READY (CB2) has already gone high,
        # so if we see it low again at the top of the loop then it's a new byte.
        PortB_DATA_TAKEN.value(0)
        in_bytes.append(int8)
        # delay loop to give the 6809 time to send the next byte (if any)
        for i in range(150):
            pass
        PortB_DATA_TAKEN.value(1)
        
    return in_bytes

def listen():
    "Wait for bytes from the 6809 and output them to the console"

    my_time = time.time()
    
    while True:
        in_bytes = get_bytes()
        if in_bytes:
             print(in_bytes)
            
    return

# Main program starts here
try:  
    time.sleep_ms(100)  # wait 100ms for 6809 to start up
    dload_exec_file("boot2.ex9")
    dload_exec_file("blink1.ex9")
    print("Download complete, listening...")
    listen()
except KeyboardInterrupt:
    print("Interrupted by user")
print("Done.")
