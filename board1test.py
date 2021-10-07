try:
    import RPi.GPIO as GPIO
except RuntimeError:
    print("Error importing RPi.GPIO")
    
try:
    import time
except RuntimeError:
    print("Error importing time")
    
assert(GPIO.getmode() == None)

GPIO.setmode(GPIO.BOARD); # use Pi connector pin numbering

# 6809 processor control (output, active-high)
RST_NMI = 24 # GP08
GPIO.setup(RST_NMI, GPIO.OUT)
GPIO.output(RST_NMI, GPIO.LOW)

time.sleep(0.3) # give the 6809 tine to come out of reset (?)

# data bus (input/output)
D0 = 11  # GP17
D1 = 12  # GP18
D2 = 13  # GP27
D3 = 15  # GP22
D4 = 16  # GP23
D5 = 19  # GP10
D6 = 21  # GP09
D7 = 23  # GP11
data_bus = [D7, D6, D5, D4, D3, D2, D1, D0]
GPIO.setup(data_bus, GPIO.IN)

# chip selects (output, active-low, pull-up)
CS0 = 26 # GP07
CS1 = 29 # GP05
CS2 = 31 # GP06
chip_selects = [CS0, CS1, CS2]
GPIO.setup(chip_selects, GPIO.OUT)
GPIO.output(chip_selects, GPIO.HIGH)
CS_portA = CS1
CS_portB = CS0
CS_handshake = CS2

# handshakes (active-low)
CA1 = 32 # GP12 - output
CA2 = 33 # GP13 - input
CB1 = 36 # GP16 - output
CB2 = 38 # GP20 - input
PortA_DATA_READY = CA1
PortA_DATA_TAKEN = CA2
PortB_DATA_TAKEN = CB1
PortB_DATA_READY = CB2 
GPIO.setup(PortA_DATA_READY, GPIO.OUT) # "data ready" output
GPIO.setup(PortA_DATA_TAKEN, GPIO.IN)  # "data taken" input
GPIO.setup(PortB_DATA_TAKEN, GPIO.OUT) # "data taken" output
GPIO.setup(PortB_DATA_READY, GPIO.IN)  # "data ready" input
GPIO.output([PortA_DATA_READY, PortB_DATA_TAKEN], GPIO.HIGH) # clear handshakes

# reset the 6809
# GPIO.output(proc_control, GPIO.HIGH)
# time.sleep(0.001)
# GPIO.output(proc_control, GPIO.LOW)

# setup for output to port A
GPIO.output(CS_handshake, GPIO.LOW)       # enable IC2, to pass handshake signals to/from target
time.sleep(0.000001)
GPIO.output(CS_handshake, GPIO.HIGH)
time.sleep(0.000001)
GPIO.output(CS_handshake, GPIO.LOW)

GPIO.output(CS_portB, GPIO.HIGH) # ensure port B is deselected, before we select port A
GPIO.setup(data_bus, GPIO.OUT)   # set data bus for output
GPIO.output(CS_portA, GPIO.HIGH)  # enable IC1, to pass data from the bus to port A

def bus_read_1():
    "Read the 8 bits of the data bus into a list"
    B0 = GPIO.input(D0)
    B1 = GPIO.input(D1)
    B2 = GPIO.input(D2)
    B3 = GPIO.input(D3)
    B4 = GPIO.input(D4)
    B5 = GPIO.input(D5)
    B6 = GPIO.input(D6)
    B7 = GPIO.input(D7)
    
    return [B7, B6, B5, B4, B3, B2, B1, B0]

def bus_read_int8():
    "Read the 8 bits of the data bus into an integer"
    B0 = GPIO.input(D0)
    B1 = GPIO.input(D1)
    B2 = GPIO.input(D2)
    B3 = GPIO.input(D3)
    B4 = GPIO.input(D4)
    B5 = GPIO.input(D5)
    B6 = GPIO.input(D6)
    B7 = GPIO.input(D7)
    
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

def send_byte(int8):
    "write a byte to Port A, with handshake, and read back from port B"
    # setup for output to port A
    assert(int8 < 256)
    GPIO.output(CS_portB, GPIO.HIGH) # ensure port B is deselected, before we select port A
    GPIO.setup(data_bus, GPIO.OUT)   # set data bus for output
    GPIO.output(CS_portA, GPIO.LOW)  # enable IC1, to pass data from the bus to port A

    output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
    GPIO.output(data_bus, output)
    GPIO.output(PortA_DATA_READY, GPIO.LOW)   # signal data ready
    GPIO.output(PortA_DATA_READY, GPIO.HIGH)  # clear data ready
        
    # read back
    # setup for input from port B
    GPIO.output(CS_portA, GPIO.HIGH) # ensure port A is deselected before we select port B
    GPIO.setup(data_bus, GPIO.IN)   # set data bus for input
    GPIO.output(CS_portB, GPIO.LOW)  # enable IC0, to pass data from port B to the bus
    
    # read data from bus, compare output and input
    input = bus_read()
    if input != output:
        print("output = ", output, "input = ", input)
        
    GPIO.output(PortB_DATA_TAKEN, GPIO.LOW) # signal data taken
    GPIO.output(PortB_DATA_TAKEN, GPIO.HIGH) # clear data taken
                
    GPIO.output(CS_portB, GPIO.HIGH) # disable IC0                

    return int8

def send_word(word):
    send_byte(word >> 8)
    send_byte(word & 0xFF)
    return word

def get_bytes():
    in_bytes = bytearray()
    # return None if no data ready on port B
    while GPIO.event_detected(PortB_DATA_READY):
        # Data ready, so read the bus. This assumes that the data
        # bus is set for input, and that the port B chip select
        # is active.
        GPIO.output(CS_portB, GPIO.LOW)  # enable IC0, to pass data from port B to the bus
        in_bytes.append(bus_read_int8())
        GPIO.output(CS_portB, GPIO.HIGH)  # disable IC0
        # handshake
        GPIO.output(PortB_DATA_TAKEN, GPIO.LOW) # set data taken
        # complete the handshake sequence
        GPIO.output(PortB_DATA_TAKEN, GPIO.HIGH) # clear data taken
        
    return in_bytes

def listen():
    print("Listening...")
    # setup for input from port B
    GPIO.output(CS_portA, GPIO.HIGH) # ensure port A is deselected before we select port B
    GPIO.setup(data_bus, GPIO.IN)   # set data bus for input

    my_time = time.time()
    
    while True:
        if time.time() > (my_time + 5):
#             GPIO.output(RST_NMI, GPIO.HIGH)
            time.sleep(0.1)
#             GPIO.output(RST_NMI, GPIO.LOW)
            print("blip")
            my_time = time.time()
            
        in_bytes = get_bytes()
        
        if in_bytes:
            print(str(in_bytes, encoding='utf-8'), end='')
            
    return

def dload_exec(load_addr, data, exec_addr):
    "Download bytes and execute specified address - not necessarily within the download"
    send_byte(0xAA)
    send_word(load_addr)
    send_word(len(data))

    for byte in data:
        send_byte(byte)

    send_word(exec_addr)

def dload_exec_file(filename):
    "Download and execute the specified file"
    with open (filename, 'rb') as f:
        # Get load address
        load_addr = int.from_bytes(f.read(2), "big")
        # Get data length
        length = int.from_bytes(f.read(2), "big")
        # Get data
        data = f.read(length)
        assert(length == len(data))
        # Get exec address
        exec_addr = int.from_bytes(f.read(2), "big")

        print ("load address = ", hex(load_addr),
               "length = ", length,
               "exec address = ", hex(exec_addr));
        
        dload_exec(load_addr, data, exec_addr)

# Main program starts here
GPIO.add_event_detect(PortB_DATA_READY, GPIO.FALLING)
dload_exec_file("test1.ex9")
try:  
    listen()
except KeyboardInterrupt:
    print ("Done.")
    GPIO.cleanup()
