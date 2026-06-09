import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Animated,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { PLAYER_ROLES, META_TACTICS, SPECIAL_ABILITIES, TRAINING_GUIDE, ARROW_TACTICS, REAL_TEAMS, SEASON_STORIES, FAQ, COUNTER_QUICK, ABBREVIATIONS, MATCHUP_MATRIX, CAREER_PATHS, MY_PLAYBOOK } from '@/src/data';

const LOCAL_DATA: Record<string, any[]> = {
  roles: PLAYER_ROLES,
  meta: META_TACTICS,
  skills: SPECIAL_ABILITIES,
  training: TRAINING_GUIDE,
  arrows: ARROW_TACTICS,
  teams: REAL_TEAMS,
  stories: SEASON_STORIES,
  faq: FAQ,
  quick: COUNTER_QUICK,
  abbr: ABBREVIATIONS,
  matrix: MATCHUP_MATRIX,
  paths: CAREER_PATHS,
  mystyle: MY_PLAYBOOK,
};

type SectionId = 'roles' | 'meta' | 'skills' | 'training' | 'arrows' | 'teams' | 'stories' | 'faq' | 'quick' | 'abbr' | 'matrix' | 'paths' | 'mystyle';

interface SectionDef {
  id: SectionId;
  endpoint: string;
  label_en: string;
  label_it: string;
  icon: string;
}

const SECTIONS: SectionDef[] = [
  { id: 'roles', endpoint: '/api/player-roles', label_en: 'Roles', label_it: 'Ruoli', icon: 'person-outline' },
  { id: 'meta', endpoint: '/api/meta-tactics', label_en: 'Meta', label_it: 'Meta', icon: 'trophy-outline' },
  { id: 'skills', endpoint: '/api/special-abilities', label_en: 'Skills', label_it: 'Abilità', icon: 'flash-outline' },
  { id: 'training', endpoint: '/api/training-guide', label_en: 'Training', label_it: 'Allenam.', icon: 'barbell-outline' },
  { id: 'arrows', endpoint: '/api/arrow-tactics', label_en: 'Arrows', label_it: 'Frecce', icon: 'swap-vertical-outline' },
  { id: 'teams', endpoint: '/api/real-teams', label_en: 'Teams', label_it: 'Squadre', icon: 'shield-half-outline' },
  { id: 'stories', endpoint: '/api/season-stories', label_en: 'Stories', label_it: 'Storie', icon: 'book-outline' },
  { id: 'faq', endpoint: '/api/faq', label_en: 'FAQ', label_it: 'FAQ', icon: 'help-circle-outline' },
  { id: 'quick', endpoint: '/api/counter-quick', label_en: 'Quick', label_it: 'Rapido', icon: 'flash-outline' },
  { id: 'abbr', endpoint: '/api/abbreviations', label_en: 'Legend', label_it: 'Leggenda', icon: 'list-outline' },
  { id: 'matrix', endpoint: '/api/matchup-matrix', label_en: 'Matrix', label_it: 'Matrice', icon: 'grid-outline' },
  { id: 'paths', endpoint: '/api/career-paths', label_en: 'Paths', label_it: 'Percorsi', icon: 'trending-up-outline' },
  { id: 'mystyle', endpoint: '/api/my-playbook', label_en: 'My Style', label_it: 'Mio Stile', icon: 'compass-outline' },
];

const TIER_COLORS: Record<string, string> = {
  S: NothingTheme.colors.accent,
  A: NothingTheme.colors.textPrimary,
  B: NothingTheme.colors.textTertiary,
};

export default function AcademyScreen() {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const isIt = language === 'it';

  const [section, setSection] = useState<SectionId>('roles');
  const [data, setData] = useState<Record<SectionId, any[]>>({
    roles: [], meta: [], skills: [], training: [], arrows: [], teams: [], stories: [], faq: [], quick: [], abbr: [], matrix: [], paths: [], mystyle: [],
  });
  const [loaded, setLoaded] = useState<Record<SectionId, boolean>>({
    roles: false, meta: false, skills: false, training: false, arrows: false, teams: false, stories: false, faq: false, quick: false, abbr: false, matrix: false, paths: false, mystyle: false,
  });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<any | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [fadeAnim] = useState(new Animated.Value(0));

  const fetchSection = useCallback((sec: SectionId) => {
    setData((prev) => ({ ...prev, [sec]: LOCAL_DATA[sec] || [] }));
    setLoaded((prev) => ({ ...prev, [sec]: true }));
  }, []);

  useEffect(() => {
    if (!loaded[section]) fetchSection(section);
  }, [section, loaded, fetchSection]);

  useEffect(() => {
    if (modalVisible) {
      Animated.timing(fadeAnim, { toValue: 1, duration: 200, useNativeDriver: true }).start();
    } else {
      fadeAnim.setValue(0);
    }
  }, [modalVisible]);

  const openItem = (item: any) => {
    setSelected(item);
    setModalVisible(true);
  };

  const items = data[section];

  // --- Card title/subtitle per section ---
  const cardTitle = (item: any): string => {
    switch (section) {
      case 'roles': return isIt ? item.name_it : item.name_en;
      case 'meta': return item.formation;
      case 'skills': return isIt ? item.name_it : item.name_en;
      case 'training': return item.position;
      case 'arrows': return item.formation;
      case 'teams': return item.team;
      case 'stories': return isIt ? item.title_it : item.title_en;
      case 'faq': return isIt ? item.question_it : item.question_en;
      case 'quick': return item.av;
      case 'abbr': return `${item.code}  ·  ${isIt ? item.name_it : item.name_en}`;
      case 'matrix': return item.opponent;
      case 'paths': return `${item.label}  ·  ${isIt ? item.title_it : item.title_en}`;
      case 'mystyle': return `${item.order}. ${isIt ? item.category_it : item.category_en}`;
      default: return '';
    }
  };
  const cardSubtitle = (item: any): string => {
    switch (section) {
      case 'roles': return item.position;
      case 'meta': return `TIER ${item.tier}` + (item.trending ? (isIt ? ' · DI MODA' : ' · TRENDING') : '');
      case 'skills': return item.best_role;
      case 'training': return (isIt ? item.priority_attributes_it : item.priority_attributes_en).join(' · ');
      case 'arrows': return item.arrows;
      case 'teams': return `${item.manager} · ${item.te_formation}`;
      case 'stories': return isIt ? item.subtitle_it : item.subtitle_en;
      case 'faq': return (item.category || '').toUpperCase();
      case 'quick': return `→ ${item.neu}`;
      case 'abbr': return item.example;
      case 'matrix': return `→ ${item.counter_neutral || '—'}`;
      case 'paths': return isIt ? item.subtitle_it : item.subtitle_en;
      case 'mystyle': return isIt ? item.summary_it : item.summary_en;
      default: return '';
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>ACADEMY</Text>
        <Text style={styles.headerSubtitle}>2026</Text>
      </View>

      <View style={styles.divider} />

      {/* Section selector */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.filterScroll}
        contentContainerStyle={styles.filterContainer}
      >
        {SECTIONS.map((s) => (
          <TouchableOpacity
            key={s.id}
            style={[styles.filterButton, section === s.id && styles.filterButtonActive]}
            onPress={() => setSection(s.id)}
          >
            <Ionicons
              name={s.icon as any}
              size={14}
              color={section === s.id ? NothingTheme.colors.accent : NothingTheme.colors.textSecondary}
              style={{ marginRight: 6 }}
            />
            <Text style={[styles.filterButtonText, section === s.id && styles.filterButtonTextActive]}>
              {(isIt ? s.label_it : s.label_en).toUpperCase()}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <View style={styles.divider} />

      {/* Count */}
      <View style={styles.countRow}>
        <Text style={styles.countText}>
          {items.length} {isIt ? 'ELEMENTI' : 'ITEMS'}
        </Text>
      </View>

      {/* List */}
      {loading && items.length === 0 ? (
        <View style={[styles.container, styles.centered]}>
          <ActivityIndicator size="large" color={NothingTheme.colors.accent} />
        </View>
      ) : (
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {items.map((item, index) => (
            <TouchableOpacity
              key={item.id || item.position || index}
              style={styles.card}
              onPress={() => openItem(item)}
              activeOpacity={0.7}
            >
              {section === 'meta' ? (
                <View style={[styles.tierBadge, { borderColor: TIER_COLORS[item.tier] || NothingTheme.colors.border }]}>
                  <Text style={[styles.tierBadgeText, { color: TIER_COLORS[item.tier] || NothingTheme.colors.textPrimary }]}>
                    {item.tier}
                  </Text>
                </View>
              ) : (
                <View style={styles.cardIcon}>
                  <Ionicons
                    name={SECTIONS.find((s) => s.id === section)!.icon as any}
                    size={20}
                    color={NothingTheme.colors.textPrimary}
                  />
                </View>
              )}
              <View style={styles.cardContent}>
                <Text style={styles.cardTitle}>{cardTitle(item)}</Text>
                <Text style={styles.cardSubtitle} numberOfLines={1}>{cardSubtitle(item)}</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={NothingTheme.colors.textTertiary} />
            </TouchableOpacity>
          ))}

          {items.length === 0 && !loading && (
            <View style={styles.emptyState}>
              <Text style={styles.emptyText}>{isIt ? 'Nessun dato disponibile' : 'No data available'}</Text>
            </View>
          )}
        </ScrollView>
      )}

      {/* Detail Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={modalVisible}
        onRequestClose={() => setModalVisible(false)}
      >
        <Animated.View style={[styles.modalOverlay, { opacity: fadeAnim }]}>
          <View style={[styles.modalContent, { paddingTop: insets.top + 10 }]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity style={styles.closeButton} onPress={() => setModalVisible(false)}>
                <Ionicons name="close" size={24} color={NothingTheme.colors.textPrimary} />
              </TouchableOpacity>
              <View style={styles.modalIconContainer}>
                <Ionicons
                  name={SECTIONS.find((s) => s.id === section)!.icon as any}
                  size={32}
                  color={NothingTheme.colors.accent}
                />
              </View>
              <Text style={styles.modalTitle}>{selected ? cardTitle(selected) : ''}</Text>
              <View style={styles.categoryBadge}>
                <Text style={styles.categoryBadgeText}>{selected ? cardSubtitle(selected) : ''}</Text>
              </View>
            </View>

            <View style={styles.dividerModal} />

            <ScrollView style={styles.modalScroll} showsVerticalScrollIndicator={false}>
              {selected && section === 'roles' && (
                <>
                  <DetailBlock label={isIt ? 'DESCRIZIONE' : 'DESCRIPTION'} value={isIt ? selected.description_it : selected.description_en} />
                  <DetailChips label={isIt ? 'ATTRIBUTI CHIAVE' : 'KEY ATTRIBUTES'} values={isIt ? selected.key_attributes_it : selected.key_attributes_en} />
                  <DetailChips label={isIt ? 'MODULI MIGLIORI' : 'BEST FORMATIONS'} values={selected.best_formations} />
                  <DetailBlock label={isIt ? 'FOCUS ALLENAMENTO' : 'TRAINING FOCUS'} value={isIt ? selected.training_focus_it : selected.training_focus_en} />
                </>
              )}
              {selected && section === 'meta' && (
                <>
                  <DetailBlock label={isIt ? 'TREND 2026' : '2026 TREND'} value={selected.trending ? (isIt ? '★ Di moda adesso' : '★ Trending now') : (isIt ? 'Stabile' : 'Stable')} />
                  <DetailBlock label={isIt ? 'PERCHÉ FUNZIONA' : 'WHY IT WORKS'} value={isIt ? selected.why_it_works_it : selected.why_it_works_en} />
                  <DetailBlock label={isIt ? 'SETUP' : 'SETUP'} value={isIt ? selected.setup_it : selected.setup_en} />
                  <DetailBlock label={isIt ? 'COME CONTRASTARLA' : 'HOW TO COUNTER'} value={isIt ? selected.counter_it : selected.counter_en} />
                </>
              )}
              {selected && section === 'skills' && (
                <>
                  <DetailBlock label={isIt ? 'RUOLO MIGLIORE' : 'BEST ROLE'} value={selected.best_role} />
                  <DetailBlock label={isIt ? 'EFFETTO' : 'EFFECT'} value={isIt ? selected.effect_it : selected.effect_en} />
                  <DetailBlock label={isIt ? 'QUANDO USARLA' : 'WHEN TO USE'} value={isIt ? selected.when_to_use_it : selected.when_to_use_en} />
                </>
              )}
              {selected && section === 'training' && (
                <>
                  <DetailChips label={isIt ? 'ATTRIBUTI PRIORITARI' : 'PRIORITY ATTRIBUTES'} values={isIt ? selected.priority_attributes_it : selected.priority_attributes_en} />
                  <DetailChips label={isIt ? 'ESERCIZI CONSIGLIATI' : 'RECOMMENDED DRILLS'} values={isIt ? selected.recommended_drills_it : selected.recommended_drills_en} />
                  <DetailBlock label={isIt ? 'NOTA' : 'NOTE'} value={isIt ? selected.note_it : selected.note_en} />
                </>
              )}
              {selected && section === 'arrows' && (
                <>
                  <View style={styles.detailBlock}>
                    <Text style={styles.detailLabel}>{isIt ? 'FRECCE' : 'ARROWS'}</Text>
                    <View style={styles.arrowsBox}>
                      <Text style={styles.arrowsText}>{selected.arrows}</Text>
                    </View>
                  </View>
                  <DetailBlock label={isIt ? 'MOVIMENTI CHIAVE' : 'KEY MOVEMENTS'} value={isIt ? selected.key_movements_it : selected.key_movements_en} />
                  <DetailBlock label={isIt ? 'PERCHÉ FUNZIONA' : 'WHY IT WORKS'} value={isIt ? selected.explanation_it : selected.explanation_en} />
                </>
              )}
              {selected && section === 'stories' && (
                <>
                  <DetailBlock label={isIt ? 'MODULO USATO' : 'FORMATION USED'} value={selected.formation_used} />
                  <DetailBlock label={isIt ? 'RISULTATO' : 'OUTCOME'} value={isIt ? selected.outcome_it : selected.outcome_en} />
                  <DetailBlock label={isIt ? 'LA STORIA' : 'THE STORY'} value={isIt ? selected.story_it : selected.story_en} />
                  <DetailChips label={isIt ? 'LEZIONI CHIAVE' : 'KEY LESSONS'} values={isIt ? selected.key_lessons_it : selected.key_lessons_en} />
                </>
              )}
              {selected && section === 'faq' && (
                <>
                  <DetailBlock label={isIt ? 'RISPOSTA' : 'ANSWER'} value={isIt ? selected.answer_it : selected.answer_en} />
                </>
              )}
              {selected && section === 'quick' && (
                <>
                  <DetailBlock label={isIt ? 'AVVERSARIO' : 'OPPONENT'} value={selected.av} />
                  <DetailBlock label={isIt ? 'SE GIOCHI OFFENSIVO' : 'OFFENSIVE COUNTER'} value={selected.off} />
                  <DetailBlock label={isIt ? 'SE GIOCHI BILANCIATO' : 'NEUTRAL COUNTER'} value={selected.neu} />
                  <DetailBlock label={isIt ? 'SE GIOCHI DIFENSIVO' : 'DEFENSIVE COUNTER'} value={selected.dif} />
                </>
              )}
              {selected && section === 'abbr' && (
                <>
                  <View style={styles.detailBlock}>
                    <Text style={styles.detailLabel}>{isIt ? 'CODICE' : 'CODE'}</Text>
                    <View style={styles.arrowsBox}>
                      <Text style={styles.arrowsText}>{selected.code}</Text>
                    </View>
                  </View>
                  <DetailBlock label={isIt ? 'NOME' : 'NAME'} value={isIt ? selected.name_it : selected.name_en} />
                  <DetailBlock label={isIt ? 'ESEMPIO' : 'EXAMPLE'} value={selected.example} />
                  <DetailBlock label={isIt ? 'DESCRIZIONE' : 'DESCRIPTION'} value={isIt ? selected.description_it : selected.description_en} />
                </>
              )}
              {selected && section === 'matrix' && (
                <>
                  <DetailBlock label={isIt ? 'AVVERSARIO' : 'OPPONENT'} value={selected.opponent} />
                  <DetailBlock label={isIt ? 'CATEGORIA' : 'CATEGORY'} value={(selected.category || '').toUpperCase()} />
                  <DetailBlock label={isIt ? 'SE GIOCHI OFFENSIVO' : 'OFFENSIVE COUNTER'} value={selected.counter_offensive || '—'} />
                  <DetailBlock label={isIt ? 'SE GIOCHI BILANCIATO' : 'NEUTRAL COUNTER'} value={selected.counter_neutral || '—'} />
                  <DetailBlock label={isIt ? 'SE GIOCHI DIFENSIVO' : 'DEFENSIVE COUNTER'} value={selected.counter_defensive || '—'} />
                </>
              )}
              {selected && section === 'paths' && (
                <>
                  <View style={styles.detailBlock}>
                    <Text style={styles.detailLabel}>{isIt ? 'LIVELLO ROSA' : 'SQUAD LEVEL'}</Text>
                    <View style={styles.arrowsBox}>
                      <Text style={styles.arrowsText}>{selected.label}</Text>
                    </View>
                  </View>
                  <DetailBlock label={isIt ? 'OBIETTIVO REALISTICO' : 'EXPECTED OUTCOME'} value={isIt ? selected.expected_outcome_it : selected.expected_outcome_en} />
                  <DetailChips label={isIt ? 'MODULI CONSIGLIATI' : 'RECOMMENDED FORMATIONS'} values={selected.recommended_formations} />
                  <DetailBlock label={isIt ? 'PERCHÉ FUNZIONANO' : 'WHY THEY WORK'} value={isIt ? selected.explanation_it : selected.explanation_en} />
                  <DetailChips label={isIt ? 'PRIORITÀ ALLENAMENTO' : 'TRAINING PRIORITY'} values={isIt ? selected.training_priority_it : selected.training_priority_en} />
                  <DetailChips label={isIt ? 'EVITA' : 'AVOID'} values={isIt ? selected.avoid_it : selected.avoid_en} />
                </>
              )}
              {selected && section === 'teams' && (
                <>
                  <DetailBlock label={isIt ? 'ALLENATORE' : 'MANAGER'} value={`${selected.manager} (${selected.era})`} />
                  <DetailBlock label={isIt ? 'STILE' : 'STYLE'} value={isIt ? selected.style_it : selected.style_en} />
                  <View style={styles.detailBlock}>
                    <Text style={styles.detailLabel}>{isIt ? 'MODULO TOP ELEVEN' : 'TOP ELEVEN FORMATION'}</Text>
                    <View style={styles.arrowsBox}>
                      <Text style={styles.arrowsText}>{selected.te_formation}</Text>
                    </View>
                  </View>
                  <DetailChips label={isIt ? 'ATTRIBUTI CHIAVE' : 'KEY ATTRIBUTES'} values={isIt ? selected.key_attributes_it : selected.key_attributes_en} />
                  <View style={styles.detailBlock}>
                    <Text style={styles.detailLabel}>{isIt ? 'FRECCE' : 'ARROWS'}</Text>
                    <View style={styles.arrowsBox}>
                      <Text style={styles.arrowsText}>{selected.arrows}</Text>
                    </View>
                  </View>
                  <DetailBlock label={isIt ? 'MENTALITÀ' : 'MENTALITY'} value={selected.mentality} />
                  <DetailBlock label={isIt ? 'FILOSOFIA' : 'PHILOSOPHY'} value={isIt ? selected.philosophy_it : selected.philosophy_en} />
                  <DetailBlock label={isIt ? 'COME IMITARLA IN TOP ELEVEN' : 'HOW TO COPY IT IN TOP ELEVEN'} value={isIt ? selected.how_to_copy_it : selected.how_to_copy_en} />
                </>
              )}
              {selected && section === 'mystyle' && (
                <>
                  <DetailBlock label={isIt ? 'SINTESI' : 'SUMMARY'} value={isIt ? selected.summary_it : selected.summary_en} />
                  {((isIt ? selected.bullets_it : selected.bullets_en) || []).length > 0 && (
                    <DetailChips label={isIt ? 'PUNTI CHIAVE' : 'KEY POINTS'} values={isIt ? selected.bullets_it : selected.bullets_en} />
                  )}
                  {(isIt ? selected.table_it : selected.table_en) && (
                    <DetailTable label={isIt ? 'DETTAGLI' : 'DETAILS'} rows={isIt ? selected.table_it : selected.table_en} />
                  )}
                </>
              )}
            </ScrollView>
          </View>
        </Animated.View>
      </Modal>
    </View>
  );
}

function DetailBlock({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <View style={styles.detailBlock}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

function DetailChips({ label, values }: { label: string; values?: string[] }) {
  if (!values || values.length === 0) return null;
  return (
    <View style={styles.detailBlock}>
      <Text style={styles.detailLabel}>{label}</Text>
      <View style={styles.chipRow}>
        {values.map((v, i) => (
          <View key={i} style={styles.chip}>
            <Text style={styles.chipText}>{v}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function DetailTable({ label, rows }: { label: string; rows?: { label: string; value: string }[] | null }) {
  if (!rows || rows.length === 0) return null;
  return (
    <View style={styles.detailBlock}>
      <Text style={styles.detailLabel}>{label}</Text>
      <View style={styles.tableBox}>
        {rows.map((r, i) => (
          <View key={i} style={[styles.tableRow, i === rows.length - 1 && styles.tableRowLast]}>
            <Text style={styles.tableLabel}>{r.label}</Text>
            <Text style={styles.tableValue}>{r.value}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: NothingTheme.colors.background },
  centered: { justifyContent: 'center', alignItems: 'center' },
  header: { padding: 24, paddingBottom: 16 },
  headerTitle: { color: NothingTheme.colors.textPrimary, fontSize: 28, fontWeight: '700', letterSpacing: 2 },
  headerSubtitle: { color: NothingTheme.colors.accent, fontSize: 28, fontWeight: '700', letterSpacing: 2, marginTop: -4 },
  divider: { height: 1, backgroundColor: NothingTheme.colors.divider, marginHorizontal: 24 },
  dividerModal: { height: 1, backgroundColor: NothingTheme.colors.divider },
  filterScroll: { flexGrow: 0 },
  filterContainer: { paddingHorizontal: 24, paddingVertical: 16, gap: 8 },
  filterButton: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 16, paddingVertical: 8, borderRadius: 4,
    backgroundColor: NothingTheme.colors.surface, borderWidth: 1,
    borderColor: NothingTheme.colors.border, marginRight: 8,
  },
  filterButtonActive: { backgroundColor: NothingTheme.colors.accentMuted, borderColor: NothingTheme.colors.accent },
  filterButtonText: { color: NothingTheme.colors.textSecondary, fontSize: 11, fontWeight: '600', letterSpacing: 1 },
  filterButtonTextActive: { color: NothingTheme.colors.accent },
  countRow: { paddingHorizontal: 24, paddingVertical: 12 },
  countText: { color: NothingTheme.colors.textTertiary, fontSize: 10, fontWeight: '600', letterSpacing: 2 },
  scrollView: { flex: 1 },
  scrollContent: { padding: 24, paddingTop: 0, paddingBottom: 100 },
  card: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface, borderRadius: 8, padding: 16,
    marginBottom: 8, borderWidth: 1, borderColor: NothingTheme.colors.border,
  },
  cardIcon: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: NothingTheme.colors.background,
    borderWidth: 1, borderColor: NothingTheme.colors.border, alignItems: 'center', justifyContent: 'center', marginRight: 14,
  },
  tierBadge: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: NothingTheme.colors.background,
    borderWidth: 2, alignItems: 'center', justifyContent: 'center', marginRight: 14,
  },
  tierBadgeText: { fontSize: 18, fontWeight: '700' },
  cardContent: { flex: 1, marginRight: 12 },
  cardTitle: { color: NothingTheme.colors.textPrimary, fontSize: 14, fontWeight: '600', marginBottom: 4 },
  cardSubtitle: { color: NothingTheme.colors.textTertiary, fontSize: 12 },
  emptyState: { alignItems: 'center', paddingVertical: 60 },
  emptyText: { color: NothingTheme.colors.textTertiary, fontSize: 14 },
  // Modal
  modalOverlay: { flex: 1, backgroundColor: NothingTheme.colors.background },
  modalContent: { flex: 1 },
  modalHeader: { padding: 24, alignItems: 'center' },
  closeButton: {
    position: 'absolute', right: 24, top: 24, width: 40, height: 40, borderRadius: 20,
    backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border,
    alignItems: 'center', justifyContent: 'center',
  },
  modalIconContainer: {
    width: 64, height: 64, borderRadius: 32, backgroundColor: NothingTheme.colors.accentMuted,
    alignItems: 'center', justifyContent: 'center', marginBottom: 16,
  },
  modalTitle: { color: NothingTheme.colors.textPrimary, fontSize: 20, fontWeight: '700', textAlign: 'center', marginBottom: 12, paddingHorizontal: 48 },
  categoryBadge: {
    backgroundColor: NothingTheme.colors.surface, paddingHorizontal: 12, paddingVertical: 4,
    borderRadius: 4, borderWidth: 1, borderColor: NothingTheme.colors.border,
  },
  categoryBadgeText: { color: NothingTheme.colors.textSecondary, fontSize: 10, fontWeight: '600', letterSpacing: 2 },
  modalScroll: { flex: 1, padding: 24 },
  detailBlock: { marginBottom: 24 },
  detailLabel: { color: NothingTheme.colors.textTertiary, fontSize: 10, fontWeight: '700', letterSpacing: 2, marginBottom: 8 },
  detailValue: { color: NothingTheme.colors.textSecondary, fontSize: 15, lineHeight: 24 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border,
    borderRadius: 4, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, marginBottom: 8,
  },
  chipText: { color: NothingTheme.colors.textPrimary, fontSize: 12, fontWeight: '500' },
  arrowsBox: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderWidth: 1,
    borderColor: NothingTheme.colors.accent,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  arrowsText: {
    color: NothingTheme.colors.accent,
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 1,
  },
  tableBox: {
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    borderRadius: 8,
    overflow: 'hidden',
  },
  tableRow: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: NothingTheme.colors.divider,
    gap: 12,
  },
  tableRowLast: {
    borderBottomWidth: 0,
  },
  tableLabel: {
    color: NothingTheme.colors.accent,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    width: 120,
  },
  tableValue: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    lineHeight: 18,
    flex: 1,
  },
});
