import React from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { LanguageProvider } from '@/src/context/LanguageContext';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <LanguageProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: '#0a0f1a' },
            animation: 'slide_from_right',
          }}
        >
          <Stack.Screen name="index" />
          <Stack.Screen name="(tabs)" />
        </Stack>
      </LanguageProvider>
    </SafeAreaProvider>
  );
}
