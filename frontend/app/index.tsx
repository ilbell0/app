import React, { useEffect } from 'react';
import { View, StyleSheet, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';

export default function Index() {
  const router = useRouter();

  useEffect(() => {
    // Go directly to the main app (no login required - it's a wiki/manual)
    const timer = setTimeout(() => {
      router.replace('/(tabs)');
    }, 500);
    
    return () => clearTimeout(timer);
  }, []);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#10b981" />
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
});
