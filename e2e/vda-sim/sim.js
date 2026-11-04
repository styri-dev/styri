// A simulated VDA 5050 vehicle: vda-5050-lib's virtual AGV, with a real factsheet
// (the library's is empty). Independent of Styri's code, so it catches our misreadings
// of the spec. Configured by environment:
//
//   BROKER_URL  mqtt://broker:1883       MANUFACTURER  acme
//   SERIAL      SN-0007                  VDA_VERSION   2.1.0 or 2.0.0
//   MQTT_USER / MQTT_PASSWORD            INTERFACE     uagv
//   START_NODE / START_X / START_Y       MAP_ID        plant-a
const { AgvController, VirtualAgvAdapter } = require("vda-5050-lib");

const env = (name, fallback) => process.env[name] || fallback;
const manufacturer = env("MANUFACTURER", "acme");
const serialNumber = env("SERIAL", "SN-0001");
const version = env("VDA_VERSION", "2.1.0");

const factsheet = require("./factsheet.json");

async function main() {
  const controller = new AgvController(
    { manufacturer, serialNumber },
    {
      interfaceName: env("INTERFACE", "uagv"),
      vdaVersion: version,
      transport: {
        brokerUrl: env("BROKER_URL", "mqtt://localhost:1883"),
        username: process.env.MQTT_USER,
        password: process.env.MQTT_PASSWORD,
      },
    },
    { agvAdapterType: VirtualAgvAdapter },
    {
      initialPosition: {
        mapId: env("MAP_ID", "plant-a"),
        x: Number(env("START_X", 0)),
        y: Number(env("START_Y", 0)),
        theta: 0,
        lastNodeId: env("START_NODE", ""),
      },
      vehicleSpeed: Number(env("SPEED", 1)),
      // vda-5050-lib reads allowedDeviationXy; the standard's field, which Styri sends, is
      // allowedDeviationXY. So it falls back to this: wide enough for the demo's longest edge.
      agvNormalDeviationXyTolerance: 7,
    },
  );
  await controller.start();
  controller.updateFactsheet(factsheet);
  console.log(`${manufacturer}/${serialNumber} up, VDA 5050 ${version}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
