import axios from "axios";

export const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const TOKEN_KEY = "campus_synapse_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.clear();
}

const client = axios.create({ baseURL: API_BASE });

// The token is the only credential. No X-API-Key, no X-User-ID: identity comes
// from the signed JWT, and the backend re-reads the account on every request.
client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // A 401 means the token expired, was tampered with, or the account was
    // deactivated server-side. In every case the session is over.
    if (error.response?.status === 401) {
      clearSession();
      if (window.location.pathname !== "/login") {
        window.location.replace("/login");
      }
    }
    return Promise.reject(error);
  },
);

/** Pull a readable message out of a FastAPI error response. */
export function apiError(error, fallback = "Something went wrong.") {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail[0]?.msg || fallback;
  }
  return error?.message || fallback;
}

export default client;
