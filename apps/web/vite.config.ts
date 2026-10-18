import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ command, mode }) => {
  const screen = mode === "order" || mode === "fulfill" ? mode : "combined";
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const api = process.env.VITE_API_BASE_URL ?? env.VITE_API_BASE_URL;
  if (command === "build" && screen !== "combined") {
    if (!api || new URL(api).protocol !== "https:") {
      throw new Error("Separate site builds require VITE_API_BASE_URL with the hosted HTTPS API origin.");
    }
  }
  return {
    define: { "import.meta.env.VITE_APP_SCREEN": JSON.stringify(screen) },
    build: { outDir: screen === "combined" ? "dist" : `dist/${screen}` },
    server: {
      proxy: { "/v1": { target: "http://127.0.0.1:8000", ws: true } },
    },
    plugins: [{
      name: "site-title",
      transformIndexHtml: (html: string) => html.replace("<title>FullFill</title>", `<title>FullFill${screen === "order" ? " · Order" : screen === "fulfill" ? " · Kitchen" : ""}</title>`),
    }],
  };
});
