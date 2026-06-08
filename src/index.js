
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { AuthProvider } from "react-oidc-context";

const cognitoAuthConfig = {
  authority: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_chmfUS9qu",
  client_id: "4pbcgreall8s87rhp4qj0al4pj",
  redirect_uri: "http://localhost:3000",
  response_type: "code",
  scope: "phone openid email",
  automaticSilentRenew: true,
};
const root = ReactDOM.createRoot(document.getElementById("root"));

root.render(
  <React.StrictMode>
    <AuthProvider {...cognitoAuthConfig}>
      <App />
    </AuthProvider>
  </React.StrictMode>
);