import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';

export default function AuthCallback() {
  const router = useRouter();
  const { processCallback } = useAuth();
  const { t } = useLanguage();
  const hasProcessed = useRef(false);

  useEffect(() => {
    // Prevent double processing in StrictMode
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const handleCallback = async () => {
      try {
        if (Platform.OS !== 'web') {
          router.replace('/(auth)/login');
          return;
        }

        // Extract session_id from URL hash
        const hash = window.location.hash;
        const sessionIdMatch = hash.match(/session_id=([^&]+)/);
        
        if (!sessionIdMatch) {
          console.error('No session_id found in URL');
          router.replace('/(auth)/login');
          return;
        }

        const sessionId = sessionIdMatch[1];
        await processCallback(sessionId);
        
        // Clear the hash and redirect
        window.history.replaceState(null, '', window.location.pathname);
        router.replace('/(tabs)');
      } catch (error) {
        console.error('Callback error:', error);
        router.replace('/(auth)/login');
      }
    };

    handleCallback();
  }, []);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#10b981" />
      <Text style={styles.text}>{t('loading')}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0f1a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: {
    color: '#fff',
    marginTop: 16,
    fontSize: 16,
  },
});
