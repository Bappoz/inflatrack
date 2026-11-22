"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Send, X } from "lucide-react";
import Image from "next/image";

type ChatMessage = {
  role: "assistant" | "user";
  text: string;
};

export default function FeliciaChat() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "Olá! Sou a Felicia. Em breve poderei consultar os dados do InflaTrack e ajudar você.",
    },
  ]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;

    setMessages((current) => [
      ...current,
      { role: "user", text },
      {
        role: "assistant",
        text: "Recebi sua mensagem. A conexão inteligente estará disponível na próxima etapa.",
      },
    ]);
    setMessage("");
  }

  return (
    <>
      {open && (
        <section
          className="felicia-chat-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="felicia-chat-title"
        >
          <header className="felicia-chat-header">
            <div className="felicia-chat-person">
              <Image
                src="/Felicia.svg"
                alt=""
                width={40}
                height={40}
                aria-hidden="true"
              />
              <div>
                <strong id="felicia-chat-title">Felicia</strong>
                <span>Assistente InflaTrack</span>
              </div>
            </div>
            <button
              type="button"
              className="felicia-chat-close"
              aria-label="Fechar conversa"
              onClick={() => setOpen(false)}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>

          <div className="felicia-chat-messages" aria-live="polite">
            {messages.map((item, index) => (
              <div
                className={`felicia-chat-message felicia-chat-message-${item.role}`}
                key={`${item.role}-${index}`}
              >
                {item.text}
              </div>
            ))}
          </div>

          <form className="felicia-chat-form" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Digite sua pergunta..."
              aria-label="Mensagem para a Felicia"
            />
            <button type="submit" aria-label="Enviar mensagem" disabled={!message.trim()}>
              <Send size={17} aria-hidden="true" />
            </button>
          </form>
        </section>
      )}

      <button
        type="button"
        className="felicia-chat-trigger"
        aria-label={open ? "Fechar conversa com a Felicia" : "Abrir conversa com a Felicia"}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Image
          src="/Felicia.svg"
          alt=""
          width={68}
          height={68}
          aria-hidden="true"
        />
      </button>
    </>
  );
}
