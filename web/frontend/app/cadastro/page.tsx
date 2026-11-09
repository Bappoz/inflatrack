"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "react-toastify";
import {
  ArrowRight,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";

export default function RegistrationPage() {
  const router = useRouter();
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [imageUnavailable, setImageUnavailable] = useState(false);
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);

    if (formData.get("password") !== formData.get("confirm-password")) {
      setMessage("As senhas não coincidem.");
      return;
    }

    setIsSubmitting(true);
    setMessage("");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const response = await fetch(`${apiUrl.replace(/\/$/, "")}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formData.get("name"),
          email: formData.get("email"),
          password: formData.get("password"),
          confirm_password: formData.get("confirm-password"),
        }),
      });
      const result: {
        detail?: string | { msg?: string }[];
        confirmation_required?: boolean;
      } = await response.json();

      if (!response.ok) {
        const detail = Array.isArray(result.detail)
          ? result.detail.map((error) => error.msg).filter(Boolean).join(" ")
          : result.detail;
        const errorMessage = detail || "Não foi possível criar a conta. Tente novamente.";
        setMessage(errorMessage);
        toast.error(errorMessage);
        return;
      }

      toast.success(
        result.confirmation_required
          ? "Conta criada. Confira seu e-mail e depois entre na sua conta."
          : "Conta criada com sucesso. Faça login para continuar.",
      );
      form.reset();
      router.replace("/login");
    } catch {
      const errorMessage = "Não foi possível conectar ao serviço de cadastro. Tente novamente.";
      setMessage(errorMessage);
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-page registration-page">
      <section className="login-panel" aria-labelledby="registration-title">
        <div className="login-content" id="inicio">
          <div className="section-label">
            <span className="section-label-dot" />
            INFLATRACK
          </div>
          <h1 id="registration-title">Crie sua conta.</h1>
          <p className="login-intro">
            Acompanhe índices de preços e indicadores econômicos em um só lugar.
          </p>

          <form className="login-form registration-form" onSubmit={handleSubmit}>
            <label htmlFor="name">Nome</label>
            <div className="input-wrap">
              <UserRound aria-hidden="true" size={18} />
              <input
                id="name"
                name="name"
                type="text"
                placeholder="Seu nome completo"
                autoComplete="name"
                required
              />
            </div>

            <label htmlFor="email">E-mail</label>
            <div className="input-wrap">
              <Mail aria-hidden="true" size={18} />
              <input
                id="email"
                name="email"
                type="email"
                placeholder="voce@exemplo.com"
                autoComplete="email"
                required
              />
            </div>

            <label htmlFor="password">Senha</label>
            <div className="input-wrap">
              <LockKeyhole aria-hidden="true" size={18} />
              <input
                id="password"
                name="password"
                type={passwordVisible ? "text" : "password"}
                placeholder="Mínimo de 8 caracteres"
                autoComplete="new-password"
                minLength={8}
                required
              />
              <button
                className="visibility-button"
                type="button"
                aria-label={passwordVisible ? "Ocultar senha" : "Mostrar senha"}
                onClick={() => setPasswordVisible(!passwordVisible)}
              >
                {passwordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>

            <label htmlFor="confirm-password">Confirme sua senha</label>
            <div className="input-wrap">
              <LockKeyhole aria-hidden="true" size={18} />
              <input
                id="confirm-password"
                name="confirm-password"
                type={passwordVisible ? "text" : "password"}
                placeholder="Digite sua senha novamente"
                autoComplete="new-password"
                minLength={8}
                required
              />
            </div>

            <button className="submit-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Criando conta..." : "Criar minha conta"}
              <ArrowRight aria-hidden="true" size={18} />
            </button>
            <p className="form-message" role="status" aria-live="polite">
              {message}
            </p>
          </form>

          <p className="signup-prompt">
            Já tem uma conta?{" "}
            <Link className="text-button signup-link" href="/login">
              Entrar
            </Link>
          </p>
        </div>
      </section>

      <aside className="visual-panel" aria-label="Índices de inflação e indicadores econômicos">
        <div className="artwork-wrap">
          {imageUnavailable ? (
            <div className="artwork-fallback" role="img" aria-label="Painel de indicadores econômicos">
              <span>ÍNDICES DE PREÇOS</span>
              <div className="fallback-chart" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
                <i />
              </div>
              <strong>Os dados que ajudam a entender o custo de vida.</strong>
            </div>
          ) : (
            <Image
              className="investment-artwork"
              src="/Home.svg"
              alt="Ilustração sobre inflação e indicadores econômicos"
              width={1080}
              height={1080}
              priority
              onError={() => setImageUnavailable(true)}
            />
          )}
          <div className="artwork-caption">
            <span className="caption-kicker">ACOMPANHAMENTO CONTÍNUO</span>
            <p>IPCA, INPC e outros indicadores em perspectiva.</p>
          </div>
        </div>
        <div className="visual-bottomline">
          <ShieldCheck aria-hidden="true" size={15} />
          Dados organizados para decisões mais conscientes
        </div>
      </aside>
    </main>
  );
}