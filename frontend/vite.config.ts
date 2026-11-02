import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev proxy: keeps frontend + backend same-origin so HttpOnly session cookies
// (SameSite=Lax) are sent on every API call. Without this, localhost:5173
// talking to 127.0.0.1:8000 is cross-origin and SameSite=Lax drops the
// session cookie on every fetch, causing immediate logout after login.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
