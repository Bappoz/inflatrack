import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Criar conta | Inflatrack",
  description: "Crie sua conta Inflatrack para acompanhar indicadores econômicos.",
};

export default function RegistrationLayout({ children }: Readonly<{ children: ReactNode }>) {
  return children;
}