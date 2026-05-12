# Connecting to Cadence VM via RDP

## Prerequisites

1. **Ensure VM is running**:
   ```bash
   VBoxManage startvm "cadence" --type headless
   # Wait for network (20-30 seconds)
   sleep 25
   ping -c 1 192.168.58.10
   ```

2. **VRDE is enabled** on port `3389`

## Option 1: Using Remmina (GUI)

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

## Option 2: Using xfreerdp (command line)

```bash
xfreerdp /u:host /p:linuxserver /v:192.168.58.10
```

Or with compression:
```bash
xfreerdp /u:host /p:linuxserver /v:192.168.58.10 /compression +clipboard
```

## Option 3: Using rdesktop

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