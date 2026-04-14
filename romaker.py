# Create a bytearray of 8192 bytes, filled with 0xFF
rom_data = bytearray([0xFF] * 8192)

with open('boot.ex9', 'rb') as f:
    # Read the contents of the file into the bytearray
    load_address = int.from_bytes(f.read(2), byteorder='big')
    data_length = int.from_bytes(f.read(2), byteorder='big')
    file_data = f.read(data_length)
    exec_address = int.from_bytes(f.read(2), byteorder='big')
    print(f"Load address: {hex(load_address)}, Data length: {data_length}, Exec address: {hex(exec_address)}")
    rom_address = load_address - 0xF000  # Adjust load address to fit in 0xF000-0xFFFF
    rom_data[rom_address:rom_address + len(file_data)] = file_data
    rom_data[0x1FFE:0x2000] = exec_address.to_bytes(2, byteorder='big')

# Write the bytearray to a file
with open('boot.rom', 'wb') as f:
    f.write(rom_data)