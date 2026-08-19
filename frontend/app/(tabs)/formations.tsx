import React, { useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Animated,
  TextInput,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { useFavorites } from '@/src/context/FavoritesContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { FORMATIONS } from '@/src/data';
import PitchDiagram from '@/src/components/PitchDiagram';

interface Variant {
  name_en: string;
  name_it: string;
  mentality: string;
  mentality_it: string;
  passing_focus: string;
  passing_focus_it: string;
  passing_style: string;
  passing_style_it: string;
  pressing: string;
  pressing_it: string;
  marking: string;
  marking_it: string;
  offside_trap: boolean;
  counter_attack: boolean;
  arrows: Record<string, string>;
  best_against: string[];
  tip_en: string;
  tip_it: string;
}

// Sistema tattico Top Eleven 2027: 11 parametri divisi in tre fasi.
interface OpponentSettings {
  // In possesso
  shooting_tendency: string;
  shooting_tendency_it: string;
  passing_style: string;
  passing_style_it: string;
  passing_type: string;
  passing_type_it: string;
  crossing_tendency: string;
  crossing_tendency_it: string;
  // In transizione
  lost_possession: string;
  lost_possession_it: string;
  won_possession: string;
  won_possession_it: string;
  mentality: string;
  mentality_it: string;
  // Non in possesso
  marking: string;
  marking_it: string;
  pressing: string;
  pressing_it: string;
  defensive_line: string;
  defensive_line_it: string;
  tackling: string;
  tackling_it: string;
  tip_en: string;
  tip_it: string;
  arrows?: Record<string, string>;
  variant?: string;
}

type PhaseField = { key: keyof OpponentSettings; label_it: string; label_en: string };

// Ordine e raggruppamento identici ai tre pannelli tattici del gioco.
const TACTIC_PHASES: { key: string; label_it: string; label_en: string; fields: PhaseField[] }[] = [
  {
    key: 'possession',
    label_it: 'IN POSSESSO',
    label_en: 'IN POSSESSION',
    fields: [
      { key: 'shooting_tendency', label_it: 'Tendenza tiro', label_en: 'Shooting tendency' },
      { key: 'passing_style', label_it: 'Stile passaggi', label_en: 'Passing style' },
      { key: 'passing_type', label_it: 'Tipo di passaggi', label_en: 'Passing type' },
      { key: 'crossing_tendency', label_it: 'Tendenza cross', label_en: 'Crossing tendency' },
    ],
  },
  {
    key: 'transition',
    label_it: 'IN TRANSIZIONE',
    label_en: 'IN TRANSITION',
    fields: [
      { key: 'lost_possession', label_it: 'Possesso perso', label_en: 'Possession lost' },
      { key: 'won_possession', label_it: 'Possesso ottenuto', label_en: 'Possession won' },
      { key: 'mentality', label_it: 'Mentalità', label_en: 'Mentality' },
    ],
  },
  {
    key: 'defence',
    label_it: 'NON IN POSSESSO',
    label_en: 'OUT OF POSSESSION',
    fields: [
      { key: 'marking', label_it: 'Stile marcatura', label_en: 'Marking style' },
      { key: 'pressing', label_it: 'Pressing', label_en: 'Pressing' },
      { key: 'defensive_line', label_it: 'Linea difensiva', label_en: 'Defensive line' },
      { key: 'tackling', label_it: 'Stile contrasti', label_en: 'Tackling style' },
    ],
  },
];

interface Formation {
  id: string;
  name: string;
  description_en: string;
  description_it: string;
  positions: string[];
  strengths_en: string[];
  strengths_it: string[];
  weaknesses_en: string[];
  weaknesses_it: string[];
  tactic_type_en?: string;
  tactic_type_it?: string;
  arrows?: string;
  defense_count?: number;
  common?: boolean;
  effective_against?: string[];
  vulnerable_to?: string[];
  variants?: {
    A?: Variant;
    B?: Variant;
    C?: Variant;
  };
  opponent_settings?: {
    strong: OpponentSettings;
    equal: OpponentSettings;
    weak: OpponentSettings;
  };
}

export default function FormationsScreen() {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const { isFavorite, toggleFavorite } = useFavorites();
  const [formations, setFormations] = useState<Formation[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedFormation, setSelectedFormation] = useState<Formation | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<'strong' | 'equal' | 'weak'>('equal');
  const [modalVisible, setModalVisible] = useState(false);
  const [fadeAnim] = useState(new Animated.Value(0));
  const [defenseFilter, setDefenseFilter] = useState<'fav' | 'common' | 'all' | 3 | 4 | 5>('common');
  const [search, setSearch] = useState('');
  const [history, setHistory] = useState<Formation[]>([]);
  const modalScrollRef = useRef<ScrollView>(null);

  // cerca per nome o per numero: "3-3-2-2" trova anche moduli con notazione avanzata
  const qDigits = search.replace(/\D/g, '');
  const matchesSearch = (f: Formation) => {
    if (!search.trim()) return true;
    if (f.name.toLowerCase().includes(search.toLowerCase().trim())) return true;
    return qDigits.length > 0 && f.name.replace(/\D/g, '').includes(qDigits);
  };

  // filtro + ordinamento: i moduli comuni vengono mostrati per primi.
  // Con una ricerca attiva si ignora il filtro difesa (cerca tra tutti).
  const visibleFormations = formations
    .filter((f) =>
      search.trim()
        ? matchesSearch(f)
        : defenseFilter === 'fav'
          ? isFavorite(f.id)
          : defenseFilter === 'common'
            ? f.common
            : defenseFilter === 'all'
              ? true
              : f.defense_count === defenseFilter
    )
    .sort((a, b) => Number(b.common) - Number(a.common));

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    if (modalVisible) {
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }).start();
    } else {
      fadeAnim.setValue(0);
    }
  }, [fadeAnim, modalVisible]);

  const fetchData = async () => {
    setFormations(FORMATIONS as Formation[]);
    setLoading(false);
  };

  const getLevelLabel = (level: string) => {
    const labels: Record<string, { en: string; it: string }> = {
      strong: { en: 'STRONGER', it: 'FORTE' },
      equal: { en: 'EQUAL', it: 'PARI' },
      weak: { en: 'WEAKER', it: 'DEBOLE' },
    };
    return labels[level]?.[language] || level;
  };

  const openModal = (formation: Formation) => {
    setSelectedFormation(formation);
    setSelectedLevel('equal');
    setHistory([]);
    setModalVisible(true);
  };

  // Naviga alla scheda di un modulo citato (BATTE / VULNERABILE A) cliccandolo.
  // Spinge quello corrente nello stack per poter tornare indietro.
  const openByName = (name: string) => {
    const target = formations.find((f) => f.name === name);
    if (!target) return;
    if (selectedFormation) setHistory((h) => [...h, selectedFormation]);
    setSelectedFormation(target);
    setSelectedLevel('equal');
    modalScrollRef.current?.scrollTo({ y: 0, animated: false });
  };

  // Torna alla scheda precedente nella catena di navigazione.
  const goBack = () => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setSelectedFormation(prev);
      setSelectedLevel('equal');
      modalScrollRef.current?.scrollTo({ y: 0, animated: false });
      return h.slice(0, -1);
    });
  };

  const currentSettings = selectedFormation?.opponent_settings?.[selectedLevel];

  if (loading) {
    return (
      <View style={[styles.container, styles.centered]}>
        <ActivityIndicator size="large" color={NothingTheme.colors.accent} />
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>FORMA</Text>
        <Text style={styles.headerSubtitle}>TIONS</Text>
        <Text style={styles.headerCount}>{visibleFormations.length}</Text>
      </View>

      <View style={styles.divider} />

      {/* Search */}
      <View style={styles.searchRow}>
        <Ionicons name="search" size={16} color={NothingTheme.colors.textTertiary} />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder={language === 'it' ? 'Cerca modulo (es. 3-3-2-2)' : 'Search formation (e.g. 3-3-2-2)'}
          placeholderTextColor={NothingTheme.colors.textTertiary}
          autoCapitalize="none"
          autoCorrect={false}
        />
        {search.length > 0 && (
          <TouchableOpacity onPress={() => setSearch('')}>
            <Ionicons name="close-circle" size={16} color={NothingTheme.colors.textTertiary} />
          </TouchableOpacity>
        )}
      </View>

      {/* Defense Filter */}
      <View style={styles.defFilter}>
        <TouchableOpacity
          style={[styles.defBtn, styles.favBtn, defenseFilter === 'fav' && styles.defBtnActive]}
          onPress={() => setDefenseFilter('fav')}
        >
          <Ionicons
            name={defenseFilter === 'fav' ? 'star' : 'star-outline'}
            size={14}
            color={defenseFilter === 'fav' ? NothingTheme.colors.accent : NothingTheme.colors.textSecondary}
          />
        </TouchableOpacity>
        {([['common', language === 'it' ? 'COMUNI' : 'COMMON'], ['all', language === 'it' ? 'TUTTE' : 'ALL'], [3, 'DIF 3'], [4, 'DIF 4'], [5, 'DIF 5']] as const).map(([val, lab]) => (
          <TouchableOpacity
            key={String(val)}
            style={[styles.defBtn, defenseFilter === val && styles.defBtnActive]}
            onPress={() => setDefenseFilter(val as any)}
          >
            <Text style={[styles.defBtnText, defenseFilter === val && styles.defBtnTextActive]}>{lab}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.divider} />

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* Formation List */}
        {visibleFormations.map((formation, index) => (
          <TouchableOpacity
            key={formation.id || index}
            style={styles.formationCard}
            onPress={() => openModal(formation)}
            activeOpacity={0.7}
          >
            <View style={styles.formationInfo}>
              <View style={styles.formationHeader}>
                <Text style={styles.formationName}>{formation.name}</Text>
                {formation.common ? (
                  <View style={styles.commonBadge}>
                    <Text style={styles.commonBadgeText}>{language === 'it' ? 'COMUNE' : 'COMMON'}</Text>
                  </View>
                ) : (
                  <View style={styles.rareBadge}>
                    <Text style={styles.rareBadgeText}>{language === 'it' ? 'VARIANTE' : 'VARIANT'}</Text>
                  </View>
                )}
              </View>
              <Text style={styles.formationPositions}>
                {formation.positions?.join(' · ')}
              </Text>
            </View>
            <Ionicons 
              name="chevron-forward" 
              size={18} 
              color={NothingTheme.colors.textTertiary} 
            />
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Detail Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={modalVisible}
        onRequestClose={() => setModalVisible(false)}
      >
        <Animated.View style={[styles.modalOverlay, { opacity: fadeAnim }]}>
          <View style={[styles.modalContent, { paddingTop: insets.top + 10 }]}>
            {/* Modal Header */}
            <View style={styles.modalHeader}>
              {history.length > 0 && (
                <TouchableOpacity style={styles.backButton} onPress={goBack}>
                  <Ionicons name="arrow-back" size={22} color={NothingTheme.colors.textPrimary} />
                </TouchableOpacity>
              )}
              <TouchableOpacity
                style={styles.closeButton}
                onPress={() => setModalVisible(false)}
              >
                <Ionicons name="close" size={24} color={NothingTheme.colors.textPrimary} />
              </TouchableOpacity>
              {selectedFormation && (
                <TouchableOpacity
                  style={styles.favModalButton}
                  onPress={() => toggleFavorite(selectedFormation.id)}
                >
                  <Ionicons
                    name={isFavorite(selectedFormation.id) ? 'star' : 'star-outline'}
                    size={20}
                    color={isFavorite(selectedFormation.id) ? NothingTheme.colors.accent : NothingTheme.colors.textPrimary}
                  />
                </TouchableOpacity>
              )}
              <Text style={styles.modalTitle}>{selectedFormation?.name}</Text>
              {selectedFormation?.tactic_type_en && (
                <View style={styles.tacticTypeBadge}>
                  <Text style={styles.tacticTypeText}>
                    {language === 'it' 
                      ? selectedFormation.tactic_type_it 
                      : selectedFormation.tactic_type_en}
                  </Text>
                </View>
              )}
            </View>

            <View style={styles.dividerModal} />

            {/* Level Tabs */}
            <View style={styles.levelTabs}>
              {(['strong', 'equal', 'weak'] as const).map((level) => (
                <TouchableOpacity
                  key={level}
                  style={[
                    styles.levelTab,
                    selectedLevel === level && styles.levelTabActive,
                  ]}
                  onPress={() => setSelectedLevel(level)}
                >
                  <Text style={[
                    styles.levelTabText,
                    selectedLevel === level && styles.levelTabTextActive,
                  ]}>
                    {getLevelLabel(level)}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <ScrollView ref={modalScrollRef} style={styles.modalScroll} showsVerticalScrollIndicator={false}>
              {/* Mini-campo: posizioni del modulo + frecce dello scenario */}
              {selectedFormation?.positions && (
                <View style={styles.pitchSection}>
                  <PitchDiagram
                    positions={selectedFormation.positions}
                    arrows={currentSettings?.arrows}
                  />
                  <View style={styles.pitchLegend}>
                    <View style={styles.legendItem}>
                      <View style={[styles.legendDot, { borderColor: '#FFFFFF' }]} />
                      <Text style={styles.legendText}>{language === 'it' ? 'Avanza ↑' : 'Push up ↑'}</Text>
                    </View>
                    <View style={styles.legendItem}>
                      <View style={[styles.legendDot, { borderColor: NothingTheme.colors.accent }]} />
                      <Text style={styles.legendText}>{language === 'it' ? 'Arretra ↓' : 'Drop ↓'}</Text>
                    </View>
                  </View>
                </View>
              )}

              {/* Description */}
              <View style={styles.descriptionSection}>
                <Text style={styles.sectionLabel}>
                  {language === 'it' ? 'DESCRIZIONE' : 'DESCRIPTION'}
                </Text>
                <Text style={styles.descriptionText}>
                  {language === 'it' 
                    ? selectedFormation?.description_it 
                    : selectedFormation?.description_en}
                </Text>
              </View>

              {/* Arrows Info */}
              {selectedFormation?.arrows && (
                <View style={styles.arrowsInfo}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'FRECCE' : 'ARROWS'}
                  </Text>
                  <View style={styles.arrowsBox}>
                    <Text style={styles.arrowsText}>{selectedFormation.arrows}</Text>
                  </View>
                </View>
              )}

              {/* Impostazioni tattiche 2027: una sezione per ciascuna delle tre fasi */}
              {currentSettings && TACTIC_PHASES.map((phase) => {
                const rows = phase.fields
                  .map((f) => ({
                    field: f,
                    value: (language === 'it'
                      ? currentSettings[`${f.key}_it` as keyof OpponentSettings]
                      : currentSettings[f.key]) as string | undefined,
                  }))
                  // un parametro assente non deve rendere una riga vuota
                  .filter((r) => !!r.value);
                if (rows.length === 0) return null;
                return (
                  <View key={phase.key} style={styles.tacticsSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? phase.label_it : phase.label_en}
                    </Text>
                    <View style={styles.tacticsGrid}>
                      {rows.map((r) => (
                        <View key={r.field.key} style={styles.tacticRow}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? r.field.label_it : r.field.label_en}
                          </Text>
                          <Text style={styles.tacticValue}>{r.value}</Text>
                        </View>
                      ))}
                    </View>
                  </View>
                );
              })}

              {/* Per-scenario Arrows */}
              {currentSettings?.arrows && Object.keys(currentSettings.arrows).length > 0 && (
                <View style={styles.arrowsScenSection}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'FRECCE' : 'ARROWS'}
                  </Text>
                  <View style={styles.arrowsGrid}>
                    {Object.entries(currentSettings.arrows).map(([pos, arrow]) => (
                      <View key={pos} style={styles.arrowItem}>
                        <Text style={styles.positionLabel}>{pos}</Text>
                        <Text style={[
                          styles.arrowIcon,
                          { color: arrow === '↓'
                              ? NothingTheme.colors.accent
                              : arrow === '↑'
                                ? '#FFFFFF'
                                : NothingTheme.colors.textTertiary },
                        ]}>
                          {arrow}
                        </Text>
                      </View>
                    ))}
                  </View>
                </View>
              )}

              {/* Tip */}
              {currentSettings && (
                <View style={styles.tipSection}>
                  <Text style={styles.sectionLabel}>TIP</Text>
                  <View style={styles.tipBox}>
                    <Text style={styles.tipText}>
                      {language === 'it' ? currentSettings.tip_it : currentSettings.tip_en}
                    </Text>
                  </View>
                </View>
              )}

              {/* Matchup Matrix Reverse Lookup */}
              {(selectedFormation?.effective_against?.length || selectedFormation?.vulnerable_to?.length) ? (
                <View style={styles.tipSection}>
                  {selectedFormation?.effective_against && selectedFormation.effective_against.length > 0 && (
                    <View style={{marginBottom: 16}}>
                      <Text style={styles.sectionLabel}>
                        {language === 'it' ? `BATTE (${selectedFormation.effective_against.length})` : `BEATS (${selectedFormation.effective_against.length})`}
                      </Text>
                      <View style={{flexDirection: 'row', flexWrap: 'wrap', gap: 6}}>
                        {selectedFormation.effective_against.map((opp: string, i: number) => {
                          const exists = formations.some((f) => f.name === opp);
                          return (
                            <TouchableOpacity
                              key={i}
                              style={[styles.tipBox, styles.linkChip, {borderLeftColor: '#FFFFFF'}]}
                              onPress={() => openByName(opp)}
                              disabled={!exists}
                              activeOpacity={0.6}
                            >
                              <Text style={[styles.tipText, {fontSize: 11}]}>{opp}</Text>
                              {exists && <Ionicons name="chevron-forward" size={12} color={NothingTheme.colors.textTertiary} />}
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    </View>
                  )}
                  {selectedFormation?.vulnerable_to && selectedFormation.vulnerable_to.length > 0 && (
                    <View>
                      <Text style={styles.sectionLabel}>
                        {language === 'it' ? `VULNERABILE A (${selectedFormation.vulnerable_to.length})` : `WEAK TO (${selectedFormation.vulnerable_to.length})`}
                      </Text>
                      <View style={{flexDirection: 'row', flexWrap: 'wrap', gap: 6}}>
                        {selectedFormation.vulnerable_to.map((opp: string, i: number) => {
                          const exists = formations.some((f) => f.name === opp);
                          return (
                            <TouchableOpacity
                              key={i}
                              style={[styles.tipBox, styles.linkChip]}
                              onPress={() => openByName(opp)}
                              disabled={!exists}
                              activeOpacity={0.6}
                            >
                              <Text style={[styles.tipText, {fontSize: 11}]}>{opp}</Text>
                              {exists && <Ionicons name="chevron-forward" size={12} color={NothingTheme.colors.textTertiary} />}
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    </View>
                  )}
                </View>
              ) : null}

              {/* Strengths & Weaknesses */}
              <View style={styles.prosConsSection}>
                <View style={styles.prosConColumn}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'PUNTI FORZA' : 'STRENGTHS'}
                  </Text>
                  {(language === 'it' 
                    ? selectedFormation?.strengths_it 
                    : selectedFormation?.strengths_en
                  )?.map((item, idx) => (
                    <View key={idx} style={styles.prosConItem}>
                      <View style={styles.prosIndicator} />
                      <Text style={styles.prosConText}>{item}</Text>
                    </View>
                  ))}
                </View>

                <View style={styles.prosConColumn}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'DEBOLEZZE' : 'WEAKNESSES'}
                  </Text>
                  {(language === 'it' 
                    ? selectedFormation?.weaknesses_it 
                    : selectedFormation?.weaknesses_en
                  )?.map((item, idx) => (
                    <View key={idx} style={styles.prosConItem}>
                      <View style={styles.consIndicator} />
                      <Text style={styles.prosConText}>{item}</Text>
                    </View>
                  ))}
                </View>
              </View>
            </ScrollView>
          </View>
        </Animated.View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  centered: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    padding: 24,
    paddingBottom: 16,
    flexDirection: 'row',
    alignItems: 'flex-end',
  },
  headerTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
  },
  headerSubtitle: {
    color: NothingTheme.colors.accent,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
  },
  headerCount: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 'auto',
    marginBottom: 4,
  },
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
    marginHorizontal: 24,
  },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 24,
    marginTop: 14,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  searchInput: {
    flex: 1,
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    padding: 0,
  },
  defFilter: {
    flexDirection: 'row',
    paddingHorizontal: 24,
    paddingVertical: 14,
    gap: 8,
  },
  defBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 5,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
  },
  favBtn: {
    flex: 0,
    paddingHorizontal: 12,
    justifyContent: 'center',
  },
  defBtnActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  defBtnText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1,
  },
  defBtnTextActive: {
    color: NothingTheme.colors.accent,
  },
  dividerModal: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 24,
    paddingTop: 16,
    paddingBottom: 100,
  },
  formationCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  formationInfo: {
    flex: 1,
  },
  formationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  formationName: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 16,
    fontWeight: '600',
  },
  metaBadge: {
    backgroundColor: NothingTheme.colors.accentMuted,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 2,
  },
  metaBadgeText: {
    color: NothingTheme.colors.accent,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  commonBadge: {
    backgroundColor: NothingTheme.colors.accentMuted,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 2,
  },
  commonBadgeText: {
    color: NothingTheme.colors.accent,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  rareBadge: {
    backgroundColor: 'transparent',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 2,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  rareBadgeText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  formationPositions: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 11,
    letterSpacing: 0.5,
  },
  // Modal Styles
  modalOverlay: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  modalContent: {
    flex: 1,
  },
  modalHeader: {
    padding: 24,
    alignItems: 'center',
  },
  closeButton: {
    position: 'absolute',
    right: 24,
    top: 24,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backButton: {
    position: 'absolute',
    left: 24,
    top: 24,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  favModalButton: {
    position: 'absolute',
    right: 72,
    top: 24,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  modalTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 32,
    fontWeight: '700',
    letterSpacing: 1,
    marginBottom: 8,
  },
  tacticTypeBadge: {
    backgroundColor: NothingTheme.colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  tacticTypeText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1,
  },
  levelTabs: {
    flexDirection: 'row',
    padding: 24,
    gap: 8,
  },
  levelTab: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
  },
  levelTabActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  levelTabText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
  },
  levelTabTextActive: {
    color: NothingTheme.colors.accent,
  },
  modalScroll: {
    flex: 1,
    paddingHorizontal: 24,
  },
  sectionLabel: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 2,
    marginBottom: 12,
  },
  pitchSection: {
    marginBottom: 24,
    marginTop: 4,
  },
  pitchLegend: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 20,
    marginTop: 10,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  legendDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 1.5,
    backgroundColor: NothingTheme.colors.background,
  },
  legendText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    letterSpacing: 0.5,
  },
  descriptionSection: {
    marginBottom: 24,
  },
  descriptionText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
  },
  arrowsInfo: {
    marginBottom: 24,
  },
  arrowsBox: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  arrowsText: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
    letterSpacing: 1,
  },
  tacticsSection: {
    marginBottom: 24,
  },
  tacticsGrid: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    overflow: 'hidden',
  },
  tacticRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 14,
    borderBottomWidth: 1,
    borderBottomColor: NothingTheme.colors.border,
  },
  tacticLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
  },
  tacticValue: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 12,
    fontWeight: '600',
  },
  togglesSection: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 24,
  },
  toggleBadge: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  toggleBadgeActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  toggleText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  toggleTextActive: {
    color: NothingTheme.colors.textPrimary,
  },
  toggleValue: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
    fontWeight: '700',
  },
  toggleValueActive: {
    color: NothingTheme.colors.accent,
  },
  arrowsScenSection: {
    marginBottom: 24,
  },
  arrowsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  arrowItem: {
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 12,
    minWidth: 56,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  positionLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    marginBottom: 4,
  },
  arrowIcon: {
    fontSize: 20,
    fontWeight: '700',
  },
  tipSection: {
    marginBottom: 24,
  },
  tipBox: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 16,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    borderLeftWidth: 3,
    borderLeftColor: NothingTheme.colors.accent,
  },
  tipText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
  },
  linkChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  prosConsSection: {
    marginBottom: 40,
  },
  prosConColumn: {
    marginBottom: 20,
  },
  prosConItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 8,
    gap: 10,
  },
  prosIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.textPrimary,
    marginTop: 4,
  },
  consIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.accent,
    marginTop: 4,
  },
  prosConText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    flex: 1,
    lineHeight: 18,
  },
});
