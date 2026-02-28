import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { Platform } from 'react-native';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface User {
  user_id: string;
  email: string;
  name: string;
  picture?: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  sessionToken: string | null;
  login: () => void;
  logout: () => Promise<void>;
  processCallback: (sessionId: string) => Promise<void>;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sessionToken, setSessionToken] = useState<string | null>(null);

  const checkAuth = useCallback(async () => {
    try {
      // Skip if we're on callback page (will be handled by processCallback)
      if (Platform.OS === 'web' && window.location.hash?.includes('session_id=')) {
        setIsLoading(false);
        return;
      }

      const storedToken = await AsyncStorage.getItem('session_token');
      if (!storedToken) {
        setIsLoading(false);
        return;
      }

      const response = await axios.get(`${API_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${storedToken}` },
      });

      setUser(response.data);
      setSessionToken(storedToken);
    } catch (error) {
      console.log('Not authenticated');
      await AsyncStorage.removeItem('session_token');
      setUser(null);
      setSessionToken(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    if (Platform.OS === 'web') {
      const redirectUrl = window.location.origin + '/callback';
      window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
    }
  };

  const processCallback = async (sessionId: string) => {
    try {
      setIsLoading(true);
      const response = await axios.post(`${API_URL}/api/auth/session`, {
        session_id: sessionId,
      });

      const { user: userData, session_token } = response.data;
      
      await AsyncStorage.setItem('session_token', session_token);
      setSessionToken(session_token);
      setUser(userData);
    } catch (error) {
      console.error('Auth callback error:', error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      if (sessionToken) {
        await axios.post(`${API_URL}/api/auth/logout`, {}, {
          headers: { Authorization: `Bearer ${sessionToken}` },
        });
      }
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      await AsyncStorage.removeItem('session_token');
      setUser(null);
      setSessionToken(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        sessionToken,
        login,
        logout,
        processCallback,
        checkAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
