# Energy control baseline

Captured before implementation on 11 August 2026.

- Home Assistant checkpoint: `checkpoint_20260811_113921`, commit `61f85796`.
- Private raw Node-RED backup: `/opt/energy-optimizer/backups/checkpoint_20260811_113921/node-red-flows.raw.json` on `10.0.1.204`.
- Raw Node-RED SHA-256: `2e210ee4ca41034c15fbc8f853bc33b20114cb4467b160ab727fc11272d02432`.
- Active legacy Node-RED tab: `a2df5fa2a3506886`, `FIT Blended Dispatch (Export Setpoint Only)`.
- Legacy target flow writes `input_number.fit_target_export_setpoint_kw`; Home Assistant automation `1769678731886` converts that value into forced discharge.
- Fixed morning PV-charge-off automation: `1766169660776`.
- Fixed 10:30 PV-charge-on automation: `1766537330474`.
- Force-discharge bridge automations: `1765837567828` and `1765837657637`.
- Force-charge bridge automations: `1765837458603` and `1765837692266`.
- Existing hot-water automation: `automation.hot_water_solar_driven_with_3hr_guarantee_by_3pm`.

Earlier configuration analysis reported a plaintext EV recovery credential. A current scoped search of the active Node-RED flow and Home Assistant energy/Tesla automations found no SSH/password command, and the new EV actuator uses local Tesla BLE entities only. EV auto-control remains helper-disabled until the seven-day review and a final secret scan. The Home Assistant checkpoint and private raw backup are the authoritative rollback sources.

After the guarded flow was deployed, Node-RED `leave_front_door_open` was changed from `true` to `false`. The direct LAN `/flows` and `/diagnostics` endpoints now return HTTP 401; protected Home Assistant ingress remains the administration path.
