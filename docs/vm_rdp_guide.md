# Connecting to Cadence VM

## Prerequisites

1. **Ensure VM is running**:
   ```bash
   VBoxManage startvm "cadence" --type headless
   # Wait for network (20-30 seconds)
   sleep 25
   ping -c 1 192.168.58.10
   ```

## Option 1: Using SSH (Recommended for CLI)

SSH is recommended for running Innovus and automated flows.

```bash
# Using sshpass (with password)
sshpass -p linuxserver ssh -o StrictHostKeyChecking=no host@192.168.58.10

# Or set up passwordless SSH
ssh-copy-id host@192.168.58.10  # Run once to configure
ssh host@192.168.58.10
```

To transfer files:
```bash
# Copy to VM
scp design.gds host@192.168.58.10:/home/host/designs/

# Copy from VM
scp host@192.168.58.10:/home/host/designs/output.tar.gz .
```

## Option 2: Using RDP (GUI)

RDP requires VRDE enabled on port `3389`. Use for desktop GUI access only.

### Using Remmina (GUI)

```bash
remmina
```

Then:
1. Click **New Connection Profile** (or `Ctrl+N`)
2. Set the following:
   - **Protocol**: `RDP - Remote Desktop Protocol`
   - **Server**: `192.168.58.10` or `localhost:3389`
   - **User name**: `host`
   - **Password**: `linuxserver`
3. Click **Connect**

### Using xfreerdp (command line)

```bash
xfreerdp /u:host /p:linuxserver /v:192.168.58.10
```

Or with compression:
```bash
xfreerdp /u:host /p:linuxserver /v:192.168.58.10 /compression +clipboard
```

### Using rdesktop

```bash
rdesktop -u host -p linuxserver 192.168.58.10
```

## Troubleshooting

- **VM not running**: Run `VBoxManage startvm "cadence" --type headless`
- **Network not ready**: Wait 25+ seconds after starting VM
- **Connection refused**: Check VRDE status with:
  ```bash
  VBoxManage showvminfo "cadence" | grep VRDE
  ```
- **Authentication failed**: Use credentials `host` / `linuxserver`

## Note on Performance

RDP over host-only network (192.168.58.x) may be slower than expected. For better performance, consider:
- Reducing display resolution in VM
- Using有线连接 or 5GHz WiFi if possible