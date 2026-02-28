import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import axios from 'axios';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface Formation {
  id: string;
  name: string;
  description_en: string;
  description_it: string;
}

interface CounterTactic {
  formation: string;
  counters: string[];
  reason_en: string;
  reason_it: string;
}

export default function CountersScreen() {
  const insets = useSafeAreaInsets();
  const { t, language } = useLanguage();
  const [formations, setFormations] = useState<Formation[]>([]);
  const [counters, setCounters] = useState<CounterTactic[]>([]);
  const [selectedFormation, setSelectedFormation] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [formationsRes, countersRes] = await Promise.all([
        axios.get(`${API_URL}/api/formations`),
        axios.get(`${API_URL}/api/counters`),
      ]);

      setFormations(formationsRes.data);
      setCounters(countersRes.data);
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getFormationName = (id: string) => {
    const formation = formations.find((f) => f.id === id);
    return formation?.name || id;
  };

  const getFormationDescription = (id: string) => {
    const formation = formations.find((f) => f.id === id);
    if (!formation) return '';
    return language === 'it' ? formation.description_it : formation.description_en;
  };

  const selectedCounter = counters.find((c) => c.formation === selectedFormation);

  if (loading) {
    return (
      <View style={[styles.container, styles.centered]}>
        <ActivityIndicator size="large" color="#10b981" />
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{t('counterTactics')}</Text>
        <Text style={styles.headerSubtitle}>{t('selectFormation')}</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {/* Formation Selector */}
        <View style={styles.formationSelector}>
          {formations.map((formation) => (
            <TouchableOpacity
              key={formation.id}
              style={[
                styles.formationButton,
                selectedFormation === formation.id && styles.formationButtonActive,
              ]}
              onPress={() => setSelectedFormation(formation.id)}
            >
              <Text
                style={[
                  styles.formationButtonText,
                  selectedFormation === formation.id && styles.formationButtonTextActive,
                ]}
              >
                {formation.name}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Counter Tactics Result */}
        {selectedCounter && (
          <View style={styles.resultContainer}>
            <View style={styles.vsContainer}>
              <View style={styles.vsFormation}>
                <Text style={styles.vsLabel}>
                  {language === 'it' ? 'Avversario' : 'Opponent'}
                </Text>
                <Text style={styles.vsFormationName}>
                  {getFormationName(selectedFormation!)}
                </Text>
              </View>
              <View style={styles.vsIcon}>
                <Ionicons name="flash" size={32} color="#f59e0b" />
              </View>
              <View style={styles.vsFormation}>
                <Text style={styles.vsLabel}>{t('bestCounters')}</Text>
              </View>
            </View>

            {/* Counter formations */}
            {selectedCounter.counters.map((counterId) => (
              <View key={counterId} style={styles.counterCard}>
                <View style={styles.counterHeader}>
                  <View style={styles.counterIcon}>
                    <Ionicons name="shield-checkmark" size={24} color="#10b981" />
                  </View>
                  <Text style={styles.counterName}>{getFormationName(counterId)}</Text>
                </View>
                <Text style={styles.counterDescription}>
                  {getFormationDescription(counterId)}
                </Text>
              </View>
            ))}

            {/* Reason */}
            <View style={styles.reasonCard}>
              <View style={styles.reasonHeader}>
                <Ionicons name="bulb" size={20} color="#f59e0b" />
                <Text style={styles.reasonTitle}>{t('reason')}</Text>
              </View>
              <Text style={styles.reasonText}>
                {language === 'it' ? selectedCounter.reason_it : selectedCounter.reason_en}
              </Text>
            </View>
          </View>
        )}

        {/* Empty state */}
        {!selectedFormation && (
          <View style={styles.emptyState}>
            <Ionicons name="hand-left-outline" size={64} color="rgba(255,255,255,0.2)" />
            <Text style={styles.emptyText}>
              {language === 'it'
                ? 'Seleziona una formazione avversaria per vedere le contro-tattiche'
                : 'Select an opponent formation to see counter tactics'}
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0f1a',
  },
  centered: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    padding: 20,
    paddingBottom: 8,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  headerSubtitle: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 14,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingTop: 12,
    paddingBottom: 100,
  },
  formationSelector: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 24,
  },
  formationButton: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  formationButtonActive: {
    backgroundColor: 'rgba(16,185,129,0.2)',
    borderColor: '#10b981',
  },
  formationButtonText: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 16,
    fontWeight: '600',
  },
  formationButtonTextActive: {
    color: '#10b981',
  },
  resultContainer: {
    marginTop: 8,
  },
  vsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 20,
    marginBottom: 20,
  },
  vsFormation: {
    flex: 1,
    alignItems: 'center',
  },
  vsLabel: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 12,
    marginBottom: 4,
  },
  vsFormationName: {
    color: '#ef4444',
    fontSize: 24,
    fontWeight: 'bold',
  },
  vsIcon: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: 'rgba(245,158,11,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 16,
  },
  counterCard: {
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.3)',
  },
  counterHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  counterIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(16,185,129,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  counterName: {
    color: '#10b981',
    fontSize: 22,
    fontWeight: 'bold',
  },
  counterDescription: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 14,
    lineHeight: 20,
    paddingLeft: 52,
  },
  reasonCard: {
    backgroundColor: 'rgba(245,158,11,0.1)',
    borderRadius: 16,
    padding: 16,
    marginTop: 8,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.3)',
  },
  reasonHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  reasonTitle: {
    color: '#f59e0b',
    fontSize: 16,
    fontWeight: '600',
  },
  reasonText: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 14,
    lineHeight: 22,
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  emptyText: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 15,
    textAlign: 'center',
    marginTop: 16,
    paddingHorizontal: 40,
    lineHeight: 22,
  },
});
