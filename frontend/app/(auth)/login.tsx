import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Image,
  Dimensions,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { LinearGradient } from 'expo-linear-gradient';

const { width, height } = Dimensions.get('window');

export default function LoginScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { login } = useAuth();
  const { t, language, setLanguage } = useLanguage();

  const handleGuestAccess = () => {
    router.replace('/(tabs)');
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* Background gradient */}
      <LinearGradient
        colors={['#0a0f1a', '#1a2a3a', '#0a0f1a']}
        style={StyleSheet.absoluteFillObject}
      />
      
      {/* Language switcher */}
      <View style={styles.languageSwitch}>
        <TouchableOpacity
          style={[styles.langButton, language === 'en' && styles.langButtonActive]}
          onPress={() => setLanguage('en')}
        >
          <Text style={[styles.langText, language === 'en' && styles.langTextActive]}>EN</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.langButton, language === 'it' && styles.langButtonActive]}
          onPress={() => setLanguage('it')}
        >
          <Text style={[styles.langText, language === 'it' && styles.langTextActive]}>IT</Text>
        </TouchableOpacity>
      </View>

      {/* Logo and title */}
      <View style={styles.header}>
        <View style={styles.logoContainer}>
          <Ionicons name="football" size={80} color="#10b981" />
        </View>
        <Text style={styles.welcomeText}>{t('welcome')}</Text>
        <Text style={styles.appName}>{t('appName')}</Text>
        <Text style={styles.description}>{t('appDescription')}</Text>
      </View>

      {/* Features preview */}
      <View style={styles.features}>
        <View style={styles.featureItem}>
          <Ionicons name="grid-outline" size={24} color="#10b981" />
          <Text style={styles.featureText}>{t('formations')}</Text>
        </View>
        <View style={styles.featureItem}>
          <Ionicons name="shield-outline" size={24} color="#10b981" />
          <Text style={styles.featureText}>{t('counters')}</Text>
        </View>
        <View style={styles.featureItem}>
          <Ionicons name="search-outline" size={24} color="#10b981" />
          <Text style={styles.featureText}>{t('scout')}</Text>
        </View>
        <View style={styles.featureItem}>
          <Ionicons name="sparkles-outline" size={24} color="#10b981" />
          <Text style={styles.featureText}>{t('aiTactics')}</Text>
        </View>
      </View>

      {/* Login buttons */}
      <View style={styles.buttons}>
        {Platform.OS === 'web' && (
          <TouchableOpacity style={styles.googleButton} onPress={login}>
            <Ionicons name="logo-google" size={24} color="#fff" />
            <Text style={styles.googleButtonText}>{t('loginWithGoogle')}</Text>
          </TouchableOpacity>
        )}

        <TouchableOpacity style={styles.guestButton} onPress={handleGuestAccess}>
          <Ionicons name="person-outline" size={24} color="#10b981" />
          <Text style={styles.guestButtonText}>{t('continueAsGuest')}</Text>
        </TouchableOpacity>
      </View>

      {/* Footer */}
      <View style={[styles.footer, { paddingBottom: insets.bottom + 16 }]}>
        <Text style={styles.footerText}>Top Eleven Tactics v1.0</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0f1a',
  },
  languageSwitch: {
    flexDirection: 'row',
    position: 'absolute',
    top: 50,
    right: 20,
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 20,
    padding: 4,
    zIndex: 10,
  },
  langButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 16,
  },
  langButtonActive: {
    backgroundColor: '#10b981',
  },
  langText: {
    color: 'rgba(255,255,255,0.6)',
    fontWeight: '600',
    fontSize: 14,
  },
  langTextActive: {
    color: '#fff',
  },
  header: {
    alignItems: 'center',
    paddingTop: 60,
    paddingHorizontal: 24,
  },
  logoContainer: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: 'rgba(16,185,129,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
    borderWidth: 2,
    borderColor: 'rgba(16,185,129,0.3)',
  },
  welcomeText: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 16,
    marginBottom: 8,
  },
  appName: {
    color: '#fff',
    fontSize: 32,
    fontWeight: 'bold',
    marginBottom: 12,
    textAlign: 'center',
  },
  description: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 22,
    paddingHorizontal: 20,
  },
  features: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    paddingHorizontal: 24,
    marginTop: 40,
    gap: 16,
  },
  featureItem: {
    alignItems: 'center',
    backgroundColor: 'rgba(16,185,129,0.1)',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 16,
    minWidth: 140,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.2)',
  },
  featureText: {
    color: '#fff',
    marginTop: 8,
    fontSize: 14,
    fontWeight: '500',
  },
  buttons: {
    paddingHorizontal: 24,
    marginTop: 'auto',
    gap: 12,
  },
  googleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#4285F4',
    paddingVertical: 16,
    borderRadius: 12,
    gap: 12,
  },
  googleButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  guestButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'transparent',
    paddingVertical: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#10b981',
    gap: 12,
  },
  guestButtonText: {
    color: '#10b981',
    fontSize: 16,
    fontWeight: '600',
  },
  footer: {
    alignItems: 'center',
    marginTop: 24,
  },
  footerText: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
  },
});
