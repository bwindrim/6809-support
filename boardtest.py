import sys
import os

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    print("Error importing RPi.GPIO")
    
try:
    import time
except RuntimeError:
    print("Error importing time")
    
file_list = sys.argv        # get the argument list
prog_name = file_list.pop(0) # pop the script name off the head of the list

assert GPIO.getmode() == None

GPIO.setmode(GPIO.BOARD); # use Pi connector pin numbering

# 6809 processor control (output, active-high)
NMI = 24 # GP08
GPIO.setup(NMI, GPIO.OUT)
GPIO.output(NMI, GPIO.LOW) # set NMI low before we take the 6809 out of reset

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
bus_owner = None
GPIO.setup(data_bus, GPIO.IN)

# chip selects (output, active-low, pull-up)
CS0 = 26 # GP07
CS1 = 29 # GP05
CS2 = 31 # GP06
CS3 =  3 # GP02
CS4 =  5 # GP03
chip_selects = [CS0, CS1, CS2, CS3, CS4]
GPIO.setup(chip_selects, GPIO.OUT)
GPIO.output(chip_selects, GPIO.HIGH) # setting CS2 high resets 6809
CS_portA = CS1
CS_portB = CS0        # only port B drives the data bus
CS_handshake = CS2
CS_x_axis = CS3
CS_y_axis = CS4

# HCTL2000 control signals
HCTL_CLK =  7 # GP04
HCTL_RST = 40 # GP21
hctl_controls = [HCTL_CLK, HCTL_RST]
GPIO.setup(hctl_controls, GPIO.OUT)

# mouse button inputs
PB_1_2 = 35 # GP19
PB_2_3 = 37 # GP26
mouse_inputs = [PB_1_2, PB_2_3]
GPIO.setup(mouse_inputs, GPIO.IN, pull_up_down=GPIO.PUD_UP)

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

time.sleep(0.3) # give the 6809 time to reset, after CS2 going high above
# Enable IC2 to pass handshake signals to/from target. This also
# takes the 6809 out of reset.
GPIO.output(CS_handshake, GPIO.LOW)
time.sleep(0.3) # give the 6809 time to come out of reset (?)

# Reset both HCTL-2000s
GPIO.output(HCTL_RST, GPIO.LOW)  # reset the HCTL2000s
GPIO.output(HCTL_RST, GPIO.HIGH)
# Start the clock to the HCTL-2000s 
pwm = GPIO.PWM(HCTL_CLK, 10000)
pwm.start(50) # 50% duty cycle

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
    "Read the 8 bits of the data bus a list"
    int8 = bus_read_int8()
    return [int(x) for x in '{:08b}'.format(int8)]

def send_bytes(out_bytes):
    "write a series of bytes to Port A, with handshake, and read back from port B"
    global bus_owner # we're going to be changing the bus owner
    validate = True
    
    for int8 in out_bytes:
        assert int8 < 256
        output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
        assert bus_owner == data_bus
        GPIO.output(data_bus, output)
        GPIO.output(PortA_DATA_READY, GPIO.LOW)   # signal data ready
        # Wait for the 6809 to signal data taken.
        # We have to use event_detected() here because the 6522 is still in
        # strobe mode so we we'll miss the low state if we just poll for it.
        while False == GPIO.event_detected(PortA_DATA_TAKEN):
            pass

        GPIO.output(PortA_DATA_READY, GPIO.HIGH)  # clear data ready

        # Optional readback validation of sent byte
        if validate:
            while False == GPIO.event_detected(PortB_DATA_READY):
                pass
            
            # read back
            # setup for input from port B
            assert bus_owner == data_bus
            GPIO.setup(data_bus, GPIO.IN)  # set data bus for input, implicit change of bus_owner to None
            bus_owner = CS_portB
            GPIO.output(CS_portB, GPIO.LOW)  # enable IC0, to pass data from port B to the bus
            
            # read data from bus, compare output and input
            input = bus_read()
            if input != output:
                print("output = ", output, "input = ", input)
                
            # Note that we don't signal "data taken" during download validation,
            # as the 6809 is in strobe mode and isn't looking for it. Also,
            # signalling data taken was causing us to miss the first byte sent
            # by the downloaded program.
            GPIO.output(CS_portB, GPIO.HIGH) # disable IC0                
            GPIO.setup(data_bus, GPIO.OUT)   # set data bus for output
            bus_owner = data_bus
    return int8

def send_word(word):
    "Helper function to send a 16-bit integer, in hi-lo order"
    send_bytes(word.to_bytes(2, byteorder='big'))
    return word

def get_bytes():
    "read a (possibly empty) sequence of bytes from the 6809. Non-blocking."
    global bus_owner
    # setup for input from port B
    assert bus_owner == None
    bus_owner = CS_portB
    GPIO.output(CS_portB, GPIO.LOW)  # drive the data bus from port B

    in_bytes = bytearray() # return value, possibly empty

    # check for data ready on port B (active low)
    while GPIO.LOW == GPIO.input(PortB_DATA_READY):
        # Data ready, so read the bus and append to in_bytes.
        # This assumes that the data bus is set for input,
        # and that the port B chip select is active.
        int8 = bus_read_int8()
        # Pulse PortB_DATA_TAKEN (CB1) active low.
        # This will set PortB_DATA_READY (CB2) high immediately,
        # so if we see it low again at the top of the loop then it's a new byte.
        GPIO.output(PortB_DATA_TAKEN, GPIO.LOW)
        in_bytes.append(int8)
        # delay loop to give the 6809 time to send the next byte (if any)
        for i in range(150):
            pass
        GPIO.output(PortB_DATA_TAKEN, GPIO.HIGH)

    GPIO.output(CS_portB, GPIO.HIGH)  # stop driving the data bus from port B
    bus_owner = None
    
    return in_bytes

def listen():
    "Wait for bytes from the 6809 and output them to the console"
    assert bus_owner == None
    print("Listening...")
    GPIO.setup(data_bus, GPIO.IN)   # set data bus for input

    my_time = time.time()
    
    while True:
        if time.time() > (my_time + 5):
            GPIO.output(NMI, GPIO.HIGH)
            time.sleep(0.000001)
            GPIO.output(NMI, GPIO.LOW)
            my_time = time.time()
            
        in_bytes = get_bytes()
        if in_bytes:
             print(str(in_bytes, encoding='utf-8'), end='')
             
        chk_buttons()
        chk_x()
        chk_y()
            
    return

def dload_exec(load_addr, data, exec_addr):
    "Download bytes and execute specified address - not necessarily within the download"
    global bus_owner # we're going to be changing the bus owner
    # setup for output to port A
    assert bus_owner == None
    bus_owner = data_bus
    GPIO.output(CS_portB, GPIO.HIGH) # ensure port B isn't driving the data bus...
    GPIO.setup(data_bus, GPIO.OUT)   # ...before setting the data bus for output
    GPIO.output(CS_portA, GPIO.LOW)  # drive data from the bus to port A

    send_bytes(b'\xAA')      # send the download prefix byte
    send_word(load_addr)     # send the destination addess
    send_word(len(data))     # send the data length
    send_bytes(data)         # send the data
    send_word(exec_addr)     # send the execution address
    
    GPIO.output(CS_portA, GPIO.HIGH) # stop driving port A
    GPIO.setup(data_bus, GPIO.IN)    # and return the data bus to input
    bus_owner = None


def dload_exec_file(filename):
    "Download and execute the specified file"
    assert bus_owner == None
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

prev_buttons = [1, 1]
def chk_buttons():
    global prev_buttons
    buttons = [GPIO.input(PB_1_2), GPIO.input(PB_2_3)]
    if buttons != prev_buttons:
        print ("buttons =", buttons)
        prev_buttons = buttons

prev_x = [0, 0, 0, 0, 0, 0, 0, 0]

def chk_x():
    global bus_owner
    global prev_x
    assert bus_owner == None
    bus_owner = CS_x_axis
    GPIO.output(bus_owner, GPIO.LOW) # select the x-axis HCTL2000

    input = bus_read()
    
    if input != prev_x:
        print ("X input =", input)
        prev_x = input
        
    GPIO.output(bus_owner, GPIO.HIGH) # deselect the x-axis HCTL2000
    bus_owner = None

prev_y = [0, 0, 0, 0, 0, 0, 0, 0]

def chk_y():
    global bus_owner
    global prev_y
    assert bus_owner == None
    bus_owner = CS_y_axis
    GPIO.output(bus_owner, GPIO.LOW) # select the x-axis HCTL2000

    input = bus_read()
    
    if input != prev_y:
        print ("Y input =", input)
        prev_y = input
        
    GPIO.output(bus_owner, GPIO.HIGH) # deselect the x-axis HCTL2000
    bus_owner = None

# Main program starts here
GPIO.add_event_detect(PortA_DATA_TAKEN, GPIO.FALLING)
GPIO.add_event_detect(PortB_DATA_READY, GPIO.FALLING) # only needed for readback validation

try:  
    dload_exec_file(file_list[0])
    listen()
except KeyboardInterrupt:
    print ("Done.")
    GPIO.cleanup()
