/**
 * Minimal WebAuthn helpers: convert the server's JSON options (base64url strings)
 * to the browser's binary format and the resulting credential back to JSON.
 */

type JsonObject = Record<string, unknown>;

export function base64urlToBuffer(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

export function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) {
    return undefined;
  }
  return list.map((item: JsonObject) => ({
    type: "public-key",
    id: base64urlToBuffer(String(item.id)),
    transports: item.transports as AuthenticatorTransport[] | undefined,
  }));
}

export function toCreationOptions(options: JsonObject): PublicKeyCredentialCreationOptions {
  const user = options.user as JsonObject;
  return {
    ...(options as unknown as PublicKeyCredentialCreationOptions),
    challenge: base64urlToBuffer(String(options.challenge)),
    user: {
      id: base64urlToBuffer(String(user.id)),
      name: String(user.name),
      displayName: String(user.displayName),
    },
    excludeCredentials: descriptors(options.excludeCredentials),
  };
}

export function toRequestOptions(options: JsonObject): PublicKeyCredentialRequestOptions {
  return {
    ...(options as unknown as PublicKeyCredentialRequestOptions),
    challenge: base64urlToBuffer(String(options.challenge)),
    allowCredentials: descriptors(options.allowCredentials),
  };
}

export function credentialToJson(credential: PublicKeyCredential): JsonObject {
  const response = credential.response;
  const json: JsonObject = {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
  };
  if (response instanceof AuthenticatorAttestationResponse) {
    json.response = {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      attestationObject: bufferToBase64url(response.attestationObject),
      transports: response.getTransports(),
    };
  } else if (response instanceof AuthenticatorAssertionResponse) {
    json.response = {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      authenticatorData: bufferToBase64url(response.authenticatorData),
      signature: bufferToBase64url(response.signature),
      userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : null,
    };
  }
  return json;
}

export function passkeysSupported(): boolean {
  return typeof window !== "undefined" && "PublicKeyCredential" in window;
}
