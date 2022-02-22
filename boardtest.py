import sys

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

GPIO.setmode(GPIO.BCM); # use Broadcomm GPIO numbering

# 6809 processor control (output, active-high)
NMI = 8 # GP08
GPIO.setup(NMI, GPIO.OUT)
GPIO.output(NMI, GPIO.LOW) # set NMI low before we take the 6809 out of reset

# data bus (input/output)
D0 = 17  # GP17
D1 = 18  # GP18
D2 = 27  # GP27
D3 = 22  # GP22
D4 = 23  # GP23
D5 = 10  # GP10
D6 =  9  # GP09
D7 = 11  # GP11
data_bus = [D7, D6, D5, D4, D3, D2, D1, D0]

# chip selects (output, active-low, pull-up)
CS0 =  7 # GP07
CS1 =  5 # GP05
CS2 =  6 # GP06
CS3 =  2 # GP02
CS4 =  3 # GP03
chip_selects = [CS0, CS1, CS2, CS3, CS4]
GPIO.setup(chip_selects, GPIO.OUT)
GPIO.output(chip_selects, GPIO.HIGH) # setting CS2 high resets 6809
CS_portA = CS1
CS_portB = CS0        # only port B drives the data bus
CS_handshake = CS2
CS_x_axis = CS3
CS_y_axis = CS4

# HCTL2000 control signals
HCTL_CLK =  4 # GP04
HCTL_RST = 21 # GP21
hctl_controls = [HCTL_CLK, HCTL_RST]
GPIO.setup(hctl_controls, GPIO.OUT)

# mouse button inputs
PB_1_2 = 19 # GP19
PB_2_3 = 26 # GP26
mouse_inputs = [PB_1_2, PB_2_3]
GPIO.setup(mouse_inputs, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# handshakes (active-low)
CA1 = 12 # GP12 - output
CA2 = 13 # GP13 - input
CB1 = 16 # GP16 - output
CB2 = 20 # GP20 - input
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

bus_owner = None
bus_direction = GPIO.IN
GPIO.setup(data_bus, bus_direction)

def claim_bus(cs, dir):
    "Acquire exclusive use of the data bus, for a particular chip select"
    global bus_owner
    global bus_direction
    assert bus_owner == None
    bus_owner = cs
    GPIO.output(bus_owner, GPIO.LOW)  # enable the selected chip
    
    if bus_direction != dir:
        bus_direction = dir
        GPIO.setup(data_bus, bus_direction)

def release_bus(cs):
    "Release the previous exclusive use of the data bus"
    global bus_owner
    global bus_direction
    assert bus_owner != None
    assert bus_owner == cs
    GPIO.output(bus_owner, GPIO.HIGH)  # disable the current owning chip
    bus_owner = None
    
    if bus_direction != GPIO.IN:
        bus_direction = GPIO.IN
        GPIO.setup(data_bus, bus_direction)
        
    
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
    validate = True
    
    for int8 in out_bytes:
        assert int8 < 256
        output = [int(x) for x in '{:08b}'.format(int8)] # pythonically unpack byte to list of bits
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
            release_bus(CS_portA)
            claim_bus(CS_portB, GPIO.IN)
            
            # read data from bus, compare output and input
            input = bus_read()
            if input != output:
                print("output = ", output, "input = ", input)
                
            # Note that we don't signal "data taken" during download validation,
            # as the 6809 is in strobe mode and isn't looking for it. Also,
            # signalling data taken was causing us to miss the first byte sent
            # by the downloaded program.
            release_bus(CS_portB)
            claim_bus(CS_portA, GPIO.OUT)

def send_word(word):
    "Helper function to send a 16-bit integer, in hi-lo order"
    send_bytes(word.to_bytes(2, byteorder='big'))
    return word

def get_bytes():
    "read a (possibly empty) sequence of bytes from the 6809. Non-blocking."
    in_bytes = bytearray() # return value, possibly empty

    claim_bus(CS_portB, GPIO.IN)

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

    release_bus(CS_portB)
    
    return in_bytes

def listen():
    "Wait for bytes from the 6809 and output them to the console"
    print("Listening...")

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
        chk_pos(CS_x_axis)
        chk_pos(CS_y_axis)
            
    return

def dload_exec(load_addr, data, exec_addr):
    "Download bytes and execute specified address - not necessarily within the download"
    claim_bus(CS_portA, GPIO.OUT)

    send_bytes(b'\xAA')      # send the download prefix byte
    send_word(load_addr)     # send the destination addess
    send_word(len(data))     # send the data length
    send_bytes(data)         # send the data
    send_word(exec_addr)     # send the execution address
    
    release_bus(CS_portA)

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

prev_buttons = None
def chk_buttons():
    global prev_buttons
    buttons = [GPIO.input(PB_1_2), GPIO.input(PB_2_3)]
    if buttons != prev_buttons:
        print ("buttons =", buttons)
        prev_buttons = buttons

prev_pos = {}
prev_pos[CS_x_axis] = None
prev_pos[CS_y_axis] = None

def chk_pos(cs):
    global prev_pos

    claim_bus(cs, GPIO.IN)
    input = bus_read()
    release_bus(cs)

    if input != prev_pos[cs]:
        print ("input =", input)
        prev_pos[cs] = input
        
        
# Main program starts here
GPIO.add_event_detect(PortA_DATA_TAKEN, GPIO.FALLING)
GPIO.add_event_detect(PortB_DATA_READY, GPIO.FALLING) # only needed for readback validation

try:  
    dload_exec_file(file_list[0])
    listen()
except KeyboardInterrupt:
    print ("Done.")
    GPIO.cleanup()
