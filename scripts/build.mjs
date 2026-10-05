// Run the rollup build and exit explicitly (rollup can leave a native handle open on macOS).
import { rollup } from "rollup";
import config from "../rollup.config.js";

const configurations = Array.isArray(config) ? config : [config];
for (const current of configurations) {
  const bundle = await rollup(current);
  const outputs = Array.isArray(current.output) ? current.output : [current.output];
  for (const output of outputs) {
    await bundle.write(output);
  }
  await bundle.close();
}
process.exit(0);
