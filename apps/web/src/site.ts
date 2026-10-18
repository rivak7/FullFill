// Vite replaces this at build time; each deployed site has one purpose.
export const siteScreen: "order" | "fulfill" | "combined" = import.meta.env.VITE_APP_SCREEN ?? "combined";

export const homePath = siteScreen === "combined" ? "/fulfill" : "/";
