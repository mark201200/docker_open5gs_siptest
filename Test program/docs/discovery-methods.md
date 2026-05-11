# Device Discovery Methods

The IMS Test Program supports two methods for discovering registered devices:

1. **SIP REGISTER Discovery** (sip-proxy) - Default method
2. **Open5GS Discovery** (open5gs) - New method

## SIP REGISTER Discovery (sip-proxy)

### Overview

The default method auto-discovers devices from SIP REGISTER traffic captured by the `sip_proxy` tester API.

### When to Use

- You have `sip_proxy` running with the tester API enabled
- Devices are registering via SIP (sending REGISTER requests)
- You want automatic discovery without external dependencies

### Configuration

```yaml
transport:
  name: sip-proxy-http
  settings:
    api_base_url: http://127.0.0.1:8088
    # ... other settings

discovery:
  method: sip-proxy
  # No settings needed

devices: []  # Optional; can rely fully on discovery
```

### How It Works

1. `sip_proxy` captures SIP REGISTER requests from devices
2. For each REGISTER, it records:
   - Device IP (from Contact URI)
   - Inferred phone number (from User-Agent or other headers)
   - Optional IMSI (from SUBSCRIBE hints)
3. `ims_tester` fetches the inventory from `/tester/discovered-devices`
4. Discovered devices are merged with any statically configured devices
5. Users can then select devices interactively or via `--device` flag

### Device Selection

Devices can be selected by:
- Device ID (auto-generated from IMSI or IP)
- Phone number
- IMSI
- IP address

## Open5GS Discovery (open5gs)

### Overview

This method discovers devices from Open5GS by:
1. Querying the pdu-info API (`/api/v1/subscribers`) for active PDU sessions
2. Extracting UE IP and IMSI from each session
3. Querying MongoDB to get phone numbers (MSISDN) by IMSI

### When to Use

- You have Open5GS running with API enabled
- MongoDB is accessible from the test environment
- You prefer discovery from the core network instead of edge traffic
- Devices are in active PDU sessions (not just registered)

### Prerequisites

- Open5GS API accessible (default: `http://127.0.0.1:3000`)
- MongoDB running and reachable (default: `mongodb://127.0.0.1:27017`)
- Python `pymongo` package installed:
  ```bash
  pip install pymongo
  ```

### Configuration

```yaml
transport:
  name: sip-proxy-http  # Can be any transport; only discovery method matters
  settings:
    api_base_url: http://127.0.0.1:8088

discovery:
  method: open5gs
  settings:
    open5gs_api_url: http://127.0.0.1:3000
    mongodb_uri: mongodb://127.0.0.1:27017
    mongodb_db: open5gs  # Optional, default: open5gs
    request_timeout_seconds: 10  # Optional, default: 10

devices: []  # Optional; rely fully on discovery
```

### How It Works

1. `ims_tester` connects to Open5GS API at `open5gs_api_url`
2. Queries `/api/v1/subscribers` to get all subscribers and their active PDU sessions
3. For each session, extracts:
   - IMSI (from subscriber record)
   - UE IP (from PDU session IP allocation)
4. For each IMSI, queries MongoDB `subscribers.msisdn` to get the phone number
5. Creates DeviceProfile for each active session with:
   - `device_id`: `ue_<IMSI>`
   - `address`: UE IP
   - `metadata.imsi`: IMSI
   - `metadata.phone_number`: Phone number (if found in MongoDB)
   - `metadata.source`: "open5gs-pdu-info"

### Device Selection

Devices can be selected by:
- Device ID (format: `ue_<IMSI>`)
- Phone number (from MongoDB)
- IMSI
- IP address

### MongoDB Schema

The discoverer expects the MongoDB `subscribers` collection to have documents like:

```javascript
{
  "_id": ObjectId("..."),
  "imsi": "310410123456789",
  "msisdn": ["15551234567"],  // or "15551234567"
  // ... other subscriber data
}
```

### Troubleshooting

#### pymongo not installed

```
RuntimeError: pymongo is required for Open5GS discovery.
Install with: pip install pymongo
```

**Solution**: Install pymongo in your Python environment:
```bash
pip install pymongo
```

#### Cannot reach Open5GS API

```
RuntimeError: Cannot reach Open5GS API at http://127.0.0.1:3000: ...
```

**Solution**: Check that:
- Open5GS API is running and accessible
- `open5gs_api_url` is correct in the discovery settings
- No firewall blocks the connection

#### Cannot reach MongoDB

```
RuntimeError: Failed to get phone numbers from MongoDB: ...
```

**Solution**: Check that:
- MongoDB is running and accessible
- `mongodb_uri` is correct in the discovery settings
- MongoDB credentials (if any) are included in the URI
- No firewall blocks the connection

#### No devices discovered

If discovery returns empty:

1. Check that subscribers exist in Open5GS:
   ```bash
   curl http://127.0.0.1:3000/api/v1/subscribers
   ```

2. Check that they have active PDU sessions (check `session[].pdu_session[]`)

3. Verify phone numbers exist in MongoDB:
   ```bash
   mongosh mongodb://127.0.0.1:27017
   use open5gs
   db.subscribers.findOne({imsi: "<IMSI>"})
   ```

## Comparison

| Aspect | sip-proxy | open5gs |
|--------|-----------|---------|
| **Trigger** | SIP REGISTER traffic | Active PDU sessions |
| **Data Source** | Edge (SIP proxy) | Core (Open5GS + MongoDB) |
| **Dependencies** | sip_proxy API | Open5GS API + MongoDB + pymongo |
| **Real-time** | Yes (devices register) | Yes (active sessions) |
| **Phone Numbers** | From REGISTER | From MongoDB |
| **Setup Complexity** | Lower | Higher |
| **Best For** | Testing SIP layer | Testing IMS core + E2E |

## Switching Between Methods

To switch discovery methods, simply change the `discovery.method` in your runtime YAML:

```yaml
# Before: sip-proxy
discovery:
  method: sip-proxy

# After: open5gs
discovery:
  method: open5gs
  settings:
    open5gs_api_url: http://127.0.0.1:3000
    mongodb_uri: mongodb://127.0.0.1:27017
```

No changes needed to test files or device configurations (assuming device IDs/names are consistent).
