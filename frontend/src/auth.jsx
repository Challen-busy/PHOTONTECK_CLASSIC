import { createContext, useContext, useEffect, useState } from 'react';
import api from './api';

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/me').then(r => setUser(r.data)).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const login = async (username, password) => {
    try {
      const { data } = await api.post('/login', { username, password });
      if (data.error) return false;
      setUser(data);
      return true;
    } catch { return false; }
  };

  const logout = async () => {
    await api.post('/logout').catch(() => {});
    setUser(null);
  };

  return <Ctx.Provider value={{ user, setUser, loading, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
