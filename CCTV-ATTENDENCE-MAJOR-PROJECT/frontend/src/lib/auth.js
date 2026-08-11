export const TOKEN_KEY = "cctv_token";

export const getToken = () => {
  if (typeof window === "undefined") {
    return null;
  }
  return localStorage.getItem(TOKEN_KEY);
};

export const setToken = (token) => {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
};

export const clearToken = () => {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.removeItem(TOKEN_KEY);
};

export const decodeJwt = (token) => {
  try {
    const payloadPart = token.split(".")[1];
    const normalized = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(normalized);
    return JSON.parse(decoded);
  } catch (_error) {
    return null;
  }
};

export const isTokenExpired = (token) => {
  if (!token) {
    return true;
  }
  const payload = decodeJwt(token);
  if (!payload || !payload.exp) {
    return true;
  }
  return payload.exp * 1000 <= Date.now();
};

export const hasValidToken = () => {
  const token = getToken();
  return Boolean(token) && !isTokenExpired(token);
};

export const getTokenUser = () => {
  const token = getToken();
  if (!token || isTokenExpired(token)) {
    return null;
  }
  return decodeJwt(token);
};
