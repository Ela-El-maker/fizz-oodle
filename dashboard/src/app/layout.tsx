import type { Metadata } from "next";
import "@/app/globals.css";
import { Providers } from "@/app/providers";
import { env } from "@/shared/lib/env";

export const metadata: Metadata = {
  title: env.appName,
  description: "Official multi-agent control UI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
