# Optional Photon bridge

This is an integration placeholder, not a running service.
The backend/Photon owner can add the Spectrum TypeScript setup here.

Boundary:
- Outbound: shared Notification to DeliveryResult.
- Inbound: validate the sender/message and call the backend's normal catalog enrollment API.
- Keep Photon payloads and credentials inside the bridge.
- Python owns error/override meaning, shift totals, and catalog state.

Manager alerts, shift summaries, and text enrollment are not implemented.
