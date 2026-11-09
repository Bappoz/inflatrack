"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
} from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [imageUnavailable, setImageUnavailable] = useState(false);
  const [message, setMessage] = useState("");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    router.replace("/");
  }

  return (
    <main className="login-page">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-content" id="inicio">
          <div className="section-label">
            <span className="section-label-dot" />
            INFLATRACK
          </div>
          <h1 id="login-title">Inflação em foco. Dados com contexto.</h1>
          <p className="login-intro">
            Acompanhe índices de preços e indicadores econômicos em um só lugar.
          </p>

          <form className="login-form" onSubmit={handleSubmit}>
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

            <div className="password-label-row">
              <label htmlFor="password">Senha</label>
              <button
                className="text-button"
                type="button"
                onClick={() => setMessage("O link de recuperação estará disponível em breve.")}
              >
                Esqueceu a senha?
              </button>
            </div>
            <div className="input-wrap">
              <LockKeyhole aria-hidden="true" size={18} />
              <input
                id="password"
                name="password"
                type={passwordVisible ? "text" : "password"}
                placeholder="Sua senha"
                autoComplete="current-password"
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

            <button className="submit-button" type="submit">
              Entrar na minha conta
              <ArrowRight aria-hidden="true" size={18} />
            </button>
            <p className="form-message" role="status" aria-live="polite">
              {message}
            </p>
          </form>

          <p className="signup-prompt">
            Ainda não tem uma conta?{" "}
            <Link className="text-button signup-link" href="/cadastro">
              Criar conta <ArrowUpRight aria-hidden="true" size={14} />
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
      </aside>
    </main>
  );
}