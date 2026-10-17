import { compileFromFile } from "json-schema-to-typescript";
import { mkdir, writeFile } from "node:fs/promises";

const generated = await compileFromFile(
  "../../packages/contracts/generated/contracts.schema.json",
  {
    bannerComment: "/* Generated from Python contracts. Run make contracts; do not edit. */",
    additionalProperties: false,
    style: { singleQuote: false },
  },
);
await mkdir("src/api/generated", { recursive: true });
await writeFile("src/api/generated/contracts.ts", generated);
