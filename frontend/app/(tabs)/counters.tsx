import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import axios from 'axios';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface CounterScenario {
  mod: string;
  alt: string;
  men: string;
  pass: string;
  stile: string;
  ctrl: string;
  press: string;
  cont: string;
  marc: string;
  fuo: string;
  fr: Record<string, string>;
  w: string;
}

interface CounterEngine {
  av: string;
  cat: string;
  meta?: boolean;
  forte: CounterScenario;
  pari: CounterScenario;
  debole: CounterScenario;
}

type ScenarioLevel = 'forte' | 'pari' | 'debole';

export default function CountersScreen() {
  const insets = useSafeAreaInsets();
  const { t, language } = useLanguage();
  const [counterEngine, setCounterEngine] = useState<CounterEngine[]>([]);
  const [selectedFormation, setSelectedFormation] = useState<CounterEngine | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<ScenarioLevel>('pari');
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [searchCategory, setSearchCategory] = useState<string>('all');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const res = await axios.get(`${API_URL}/api/counter-engine`);
      setCounterEngine(res.data);
    } catch (error) {
      console.error('Error fetching counter engine data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getCategoryLabel = (cat: string) => {
    const labels: Record<string, { en: string; it: string }> = {
      att: { en: 'Attacking', it: 'Attaccante' },
      neu: { en: 'Balanced', it: 'Bilanciato' },
      dif: { en: 'Defensive', it: 'Difensivo' },
    };
    return labels[cat]?.[language] || cat;
  };

  const getCategoryColor = (cat: string) => {
    const colors: Record<string, string> = {
      att: '#ef4444',
      neu: '#f59e0b',
      dif: '#10b981',
    };
    return colors[cat] || '#6b7280';
  };

  const getLevelLabel = (level: ScenarioLevel) => {
    const labels: Record<ScenarioLevel, { en: string; it: string }> = {
      forte: { en: 'STRONGER', it: 'PIÙ FORTE' },
      pari: { en: 'EQUAL', it: 'PARI' },
      debole: { en: 'WEAKER', it: 'PIÙ DEBOLE' },
    };
    return labels[level][language];
  };

  const getLevelColor = (level: ScenarioLevel) => {
    const colors: Record<ScenarioLevel, string> = {
      forte: '#ef4444',
      pari: '#f59e0b',
      debole: '#10b981',
    };
    return colors[level];
  };

  const getArrowColor = (arrow: string) => {
    if (arrow === '↑') return '#10b981';
    if (arrow === '↓') return '#ef4444';
    return '#6b7280';
  };

  const filteredFormations = searchCategory === 'all'
    ? counterEngine
    : counterEngine.filter((ce) => ce.cat === searchCategory);

  const openModal = (formation: CounterEngine) => {
    setSelectedFormation(formation);
    setSelectedLevel('pari');
    setModalVisible(true);
  };

  const currentScenario = selectedFormation?.[selectedLevel];

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
        <Text style={styles.headerTitle}>
          {language === 'it' ? 'Counter Engine v6' : 'Counter Engine v6'}
        </Text>
        <Text style={styles.headerSubtitle}>
          {language === 'it'
            ? 'Seleziona la formazione avversaria'
            : 'Select opponent formation'}
        </Text>
      </View>

      {/* Category Filter */}
      <View style={styles.filterContainer}>
        {['all', 'att', 'neu', 'dif'].map((cat) => (
          <TouchableOpacity
            key={cat}
            style={[
              styles.filterButton,
              searchCategory === cat && styles.filterButtonActive,
              searchCategory === cat && { borderColor: cat === 'all' ? '#6366f1' : getCategoryColor(cat) },
            ]}
            onPress={() => setSearchCategory(cat)}
          >
            <Text
              style={[
                styles.filterButtonText,
                searchCategory === cat && { color: cat === 'all' ? '#6366f1' : getCategoryColor(cat) },
              ]}
            >
              {cat === 'all'
                ? language === 'it' ? 'Tutti' : 'All'
                : getCategoryLabel(cat)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {/* Formation Grid */}
        <View style={styles.formationGrid}>
          {filteredFormations.map((ce, index) => (
            <TouchableOpacity
              key={index}
              style={styles.formationCard}
              onPress={() => openModal(ce)}
            >
              <View style={styles.formationCardHeader}>
                <Text style={styles.formationName}>{ce.av}</Text>
                {ce.meta && (
                  <View style={styles.metaBadge}>
                    <Text style={styles.metaBadgeText}>META</Text>
                  </View>
                )}
              </View>
              <View style={[styles.categoryBadge, { backgroundColor: getCategoryColor(ce.cat) + '20' }]}>
                <Text style={[styles.categoryBadgeText, { color: getCategoryColor(ce.cat) }]}>
                  {getCategoryLabel(ce.cat)}
                </Text>
              </View>
              <Text style={styles.counterPreview}>
                {language === 'it' ? 'Contro: ' : 'Counter: '}{ce.pari.mod}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {filteredFormations.length === 0 && (
          <View style={styles.emptyState}>
            <Ionicons name="search-outline" size={64} color="rgba(255,255,255,0.2)" />
            <Text style={styles.emptyText}>
              {language === 'it'
                ? 'Nessuna formazione trovata'
                : 'No formations found'}
            </Text>
          </View>
        )}
      </ScrollView>

      {/* Detail Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={modalVisible}
        onRequestClose={() => setModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { paddingTop: insets.top + 10 }]}>
            {/* Modal Header */}
            <View style={styles.modalHeader}>
              <TouchableOpacity
                style={styles.closeButton}
                onPress={() => setModalVisible(false)}
              >
                <Ionicons name="close" size={28} color="#fff" />
              </TouchableOpacity>
              <View style={styles.modalTitleContainer}>
                <Text style={styles.modalSubtitle}>
                  {language === 'it' ? 'VS Avversario' : 'VS Opponent'}
                </Text>
                <Text style={styles.modalTitle}>{selectedFormation?.av}</Text>
                {selectedFormation?.meta && (
                  <View style={[styles.metaBadge, { marginTop: 8 }]}>
                    <Text style={styles.metaBadgeText}>★ META 2025</Text>
                  </View>
                )}
              </View>
            </View>

            {/* Level Tabs */}
            <View style={styles.levelTabs}>
              {(['forte', 'pari', 'debole'] as ScenarioLevel[]).map((level) => (
                <TouchableOpacity
                  key={level}
                  style={[
                    styles.levelTab,
                    selectedLevel === level && { backgroundColor: getLevelColor(level) + '30', borderColor: getLevelColor(level) },
                  ]}
                  onPress={() => setSelectedLevel(level)}
                >
                  <Text
                    style={[
                      styles.levelTabText,
                      selectedLevel === level && { color: getLevelColor(level), fontWeight: 'bold' },
                    ]}
                  >
                    {getLevelLabel(level)}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <ScrollView style={styles.modalScroll}>
              {currentScenario && (
                <>
                  {/* Recommended Formation */}
                  <View style={styles.recommendedSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'FORMAZIONE CONSIGLIATA' : 'RECOMMENDED FORMATION'}
                    </Text>
                    <View style={styles.formationBox}>
                      <Text style={styles.recommendedFormation}>{currentScenario.mod}</Text>
                      <Text style={styles.alternativeFormation}>
                        {language === 'it' ? 'Alternativa: ' : 'Alternative: '}{currentScenario.alt}
                      </Text>
                    </View>
                  </View>

                  {/* Tactical Settings Grid */}
                  <View style={styles.tacticsGrid}>
                    <View style={styles.tacticItem}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Mentalità' : 'Mentality'}
                      </Text>
                      <Text style={styles.tacticValue}>{currentScenario.men}</Text>
                    </View>
                    <View style={styles.tacticItem}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Passaggi' : 'Passing'}
                      </Text>
                      <Text style={styles.tacticValue}>{currentScenario.pass}</Text>
                    </View>
                    <View style={styles.tacticItem}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Stile' : 'Style'}
                      </Text>
                      <Text style={styles.tacticValue}>{currentScenario.stile}</Text>
                    </View>
                    <View style={styles.tacticItem}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Contrasti' : 'Tackling'}
                      </Text>
                      <Text style={styles.tacticValue}>{currentScenario.cont}</Text>
                    </View>
                    <View style={styles.tacticItem}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Marcatura' : 'Marking'}
                      </Text>
                      <Text style={styles.tacticValue}>{currentScenario.marc}</Text>
                    </View>
                    <View style={styles.tacticItem}>
                      <Text style={styles.tacticLabel}>Pressing</Text>
                      <Text style={styles.tacticValue}>{currentScenario.press}</Text>
                    </View>
                  </View>

                  {/* Special Settings (Badges) */}
                  <View style={styles.badgesRow}>
                    <View style={[
                      styles.badge,
                      currentScenario.ctrl === 'SI' ? styles.badgeActive : styles.badgeInactive,
                    ]}>
                      <Ionicons
                        name={currentScenario.ctrl === 'SI' ? 'checkmark-circle' : 'close-circle'}
                        size={18}
                        color={currentScenario.ctrl === 'SI' ? '#10b981' : '#6b7280'}
                      />
                      <Text style={[
                        styles.badgeText,
                        { color: currentScenario.ctrl === 'SI' ? '#10b981' : '#6b7280' },
                      ]}>
                        {language === 'it' ? 'Contropiede' : 'Counter'}
                      </Text>
                    </View>
                    <View style={[
                      styles.badge,
                      currentScenario.fuo === 'SI' ? styles.badgeActive : styles.badgeInactive,
                    ]}>
                      <Ionicons
                        name={currentScenario.fuo === 'SI' ? 'checkmark-circle' : 'close-circle'}
                        size={18}
                        color={currentScenario.fuo === 'SI' ? '#10b981' : '#6b7280'}
                      />
                      <Text style={[
                        styles.badgeText,
                        { color: currentScenario.fuo === 'SI' ? '#10b981' : '#6b7280' },
                      ]}>
                        {language === 'it' ? 'Fuorigioco' : 'Offside'}
                      </Text>
                    </View>
                  </View>

                  {/* Position Arrows */}
                  <View style={styles.arrowsSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'FRECCE POSIZIONI' : 'POSITION ARROWS'}
                    </Text>
                    <View style={styles.arrowsGrid}>
                      {Object.entries(currentScenario.fr).map(([position, arrow]) => (
                        <View key={position} style={styles.arrowItem}>
                          <Text style={styles.positionLabel}>{position}</Text>
                          <Text style={[styles.arrowIcon, { color: getArrowColor(arrow) }]}>
                            {arrow}
                          </Text>
                        </View>
                      ))}
                    </View>
                    <View style={styles.arrowLegend}>
                      <View style={styles.legendItem}>
                        <Text style={[styles.arrowIcon, { color: '#10b981' }]}>↑</Text>
                        <Text style={styles.legendText}>{language === 'it' ? 'Avanti' : 'Forward'}</Text>
                      </View>
                      <View style={styles.legendItem}>
                        <Text style={[styles.arrowIcon, { color: '#ef4444' }]}>↓</Text>
                        <Text style={styles.legendText}>{language === 'it' ? 'Indietro' : 'Backward'}</Text>
                      </View>
                      <View style={styles.legendItem}>
                        <Text style={[styles.arrowIcon, { color: '#6b7280' }]}>—</Text>
                        <Text style={styles.legendText}>{language === 'it' ? 'Neutro' : 'Neutral'}</Text>
                      </View>
                    </View>
                  </View>

                  {/* Tactical Tip */}
                  <View style={styles.tipSection}>
                    <View style={styles.tipHeader}>
                      <Ionicons name="bulb" size={20} color="#f59e0b" />
                      <Text style={styles.tipLabel}>
                        {language === 'it' ? 'CONSIGLIO TATTICO' : 'TACTICAL TIP'}
                      </Text>
                    </View>
                    <Text style={styles.tipText}>{currentScenario.w}</Text>
                  </View>
                </>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
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
  filterContainer: {
    flexDirection: 'row',
    paddingHorizontal: 20,
    gap: 8,
    marginBottom: 12,
  },
  filterButton: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  filterButtonActive: {
    backgroundColor: 'rgba(99,102,241,0.1)',
  },
  filterButtonText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 13,
    fontWeight: '600',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingTop: 8,
    paddingBottom: 100,
  },
  formationGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  formationCard: {
    width: '47%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  formationCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  formationName: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    flex: 1,
  },
  metaBadge: {
    backgroundColor: 'rgba(239,68,68,0.2)',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  metaBadgeText: {
    color: '#ef4444',
    fontSize: 10,
    fontWeight: 'bold',
  },
  categoryBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
    marginBottom: 8,
  },
  categoryBadgeText: {
    fontSize: 11,
    fontWeight: '600',
  },
  counterPreview: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 12,
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
  },
  // Modal Styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.9)',
  },
  modalContent: {
    flex: 1,
    backgroundColor: '#0a0f1a',
  },
  modalHeader: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  closeButton: {
    position: 'absolute',
    right: 16,
    top: 16,
    zIndex: 10,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  modalTitleContainer: {
    alignItems: 'center',
  },
  modalSubtitle: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 12,
    marginBottom: 4,
  },
  modalTitle: {
    color: '#ef4444',
    fontSize: 32,
    fontWeight: 'bold',
  },
  levelTabs: {
    flexDirection: 'row',
    padding: 16,
    gap: 8,
  },
  levelTab: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    alignItems: 'center',
  },
  levelTabText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 12,
    fontWeight: '600',
  },
  modalScroll: {
    flex: 1,
  },
  recommendedSection: {
    padding: 20,
    paddingTop: 8,
  },
  sectionLabel: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
    marginBottom: 12,
  },
  formationBox: {
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.3)',
    alignItems: 'center',
  },
  recommendedFormation: {
    color: '#10b981',
    fontSize: 28,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  alternativeFormation: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 14,
  },
  tacticsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    padding: 20,
    paddingTop: 0,
    gap: 10,
  },
  tacticItem: {
    width: '31%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 12,
    padding: 12,
    alignItems: 'center',
  },
  tacticLabel: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 10,
    marginBottom: 4,
  },
  tacticValue: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'center',
  },
  badgesRow: {
    flexDirection: 'row',
    paddingHorizontal: 20,
    gap: 12,
    marginBottom: 20,
  },
  badge: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 1,
  },
  badgeActive: {
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderColor: 'rgba(16,185,129,0.3)',
  },
  badgeInactive: {
    backgroundColor: 'rgba(107,114,128,0.1)',
    borderColor: 'rgba(107,114,128,0.2)',
  },
  badgeText: {
    fontSize: 14,
    fontWeight: '600',
  },
  arrowsSection: {
    padding: 20,
    paddingTop: 0,
  },
  arrowsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 16,
    gap: 8,
    marginBottom: 12,
  },
  arrowItem: {
    alignItems: 'center',
    width: '18%',
    padding: 8,
  },
  positionLabel: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 11,
    marginBottom: 4,
  },
  arrowIcon: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  arrowLegend: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 20,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  legendText: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 12,
  },
  tipSection: {
    margin: 20,
    marginTop: 0,
    backgroundColor: 'rgba(245,158,11,0.1)',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.3)',
  },
  tipHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 12,
  },
  tipLabel: {
    color: '#f59e0b',
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
  },
  tipText: {
    color: 'rgba(255,255,255,0.9)',
    fontSize: 14,
    lineHeight: 22,
  },
});
