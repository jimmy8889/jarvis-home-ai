// Run on the solar-monitor container, which already holds scoped InfluxDB access:
// ssh root@pilot 'docker exec -i solar-monitor node --input-type=module' < tools/influx_replay_export.mjs
import { InfluxDB } from "/app/node_modules/@influxdata/influxdb-client/dist/index.mjs";
import { getDailyFlow } from "/app/dist-server/server/influx.js";

const timezone = "Australia/Brisbane";
const startDate = process.env.REPLAY_START_LOCAL ?? "2026-07-13";
const completedDays = Number(process.env.REPLAY_DAYS ?? 29);
if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !Number.isInteger(completedDays) || completedDays < 1) {
  throw new Error("REPLAY_START_LOCAL must be YYYY-MM-DD and REPLAY_DAYS must be a positive integer");
}
const localStart = new Date(`${startDate}T00:00:00+10:00`);
const localStop = new Date(localStart.getTime() + completedDays * 86_400_000);
const start = localStart.toISOString();
const stop = localStop.toISOString();
const entities = {
  solar_kw: "pv_power_mqtt_abs",
  load_kw: "saj_home_load",
  grid_kw: "saj_ct_grid_power_total",
  soc_pct: "saj_battery_1_soc",
  import_price: "amber_express_trader_sheena_street_general_price",
  export_price: "amber_express_trader_sheena_street_feed_in_price",
};
const filter = Object.values(entities).map((value) => `r.entity_id == "${value}"`).join(" or ");
const query = `from(bucket: "${process.env.INFLUX_BUCKET}")
  |> range(start: time(v: "${start}"), stop: time(v: "${stop}"))
  |> filter(fn: (r) => r._field == "value")
  |> filter(fn: (r) => ${filter})
  |> aggregateWindow(every: 30m, fn: mean, createEmpty: false, timeSrc: "_start")
  |> keep(columns: ["_time", "_value", "_measurement", "entity_id"])`;
const api = new InfluxDB({
  url: process.env.INFLUX_URL,
  token: process.env.INFLUX_TOKEN,
}).getQueryApi(process.env.INFLUX_ORG);
const rows = await api.collectRows(query);
const byTime = new Map();
const entityToKey = Object.fromEntries(Object.entries(entities).map(([key, value]) => [value, key]));
for (const row of rows) {
  const key = entityToKey[String(row.entity_id)];
  if (!key) continue;
  const timestamp = new Date(String(row._time)).toISOString();
  const record = byTime.get(timestamp) ?? { timestamp };
  let value = Number(row._value);
  if (["solar_kw", "load_kw", "grid_kw"].includes(key) && String(row._measurement) !== "kW") value /= 1000;
  record[key] = value;
  byTime.set(timestamp, record);
}

const intervals = [];
let lastSoc = 50;
let lastImport = 0.20;
let lastExport = 0;
for (let millis = localStart.getTime(); millis < localStop.getTime(); millis += 30 * 60_000) {
  const timestamp = new Date(millis).toISOString();
  const row = byTime.get(timestamp) ?? { timestamp };
  if (Number.isFinite(row.soc_pct)) lastSoc = row.soc_pct; else row.soc_pct = lastSoc;
  if (Number.isFinite(row.import_price)) lastImport = row.import_price; else row.import_price = lastImport;
  if (Number.isFinite(row.export_price)) lastExport = row.export_price; else row.export_price = lastExport;
  if (!Number.isFinite(row.solar_kw)) row.solar_kw = 0;
  if (!Number.isFinite(row.load_kw)) row.load_kw = 1.67;
  if (!Number.isFinite(row.grid_kw)) row.grid_kw = row.load_kw - row.solar_kw;
  intervals.push(row);
}

const dates = [];
for (let index = 0; index < completedDays; index += 1) {
  dates.push(new Date(localStart.getTime() + index * 86_400_000).toLocaleDateString("en-CA", { timeZone: timezone }));
}
const flows = await Promise.all(dates.map((date) => getDailyFlow(date)));
const daily = flows.map((item) => ({
  date: item.date,
  solar_kwh: item.solar,
  home_kwh: item.home,
  grid_import_kwh: item.gridImport,
  grid_export_kwh: item.gridExport,
  battery_charge_kwh: item.batteryCharged,
  battery_discharge_kwh: item.batteryDischarged,
  tesla_kwh: item.tesla,
}));
process.stdout.write(JSON.stringify({
  intervals,
  daily,
  known_baseline: {
    near_full_cycles: 6,
    morning_soc_pct: 19.4,
    morning_fit_reserve_blocked_pct: 11.7,
    source: "29-day pre-implementation analysis",
  },
  forecast_baseline: {
    solcast_p50_mae_kwh: 12.1,
    solcast_p10_p90_coverage_pct: 57,
    source: "29-day pre-implementation analysis",
  },
}));
