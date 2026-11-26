import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Entrar | Inflatrack",
  description: "Acesse sua conta Inflatrack.",
};

export default function LoginLayout({ children }: Readonly<{ children: ReactNode }>) {
  return children;
}