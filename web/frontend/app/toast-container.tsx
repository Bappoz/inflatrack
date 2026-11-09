"use client";

import { ToastContainer } from "react-toastify";

export default function AppToastContainer() {
  return (
    <ToastContainer
      autoClose={5000}
      closeOnClick
      pauseOnFocusLoss
      pauseOnHover
      position="top-right"
      theme="colored"
    />
  );
}