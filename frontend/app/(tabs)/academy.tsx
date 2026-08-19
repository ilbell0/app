import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Modal,
  Animated,
  TextInput,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { PLAYER_ROLES, POSITION_GUIDE, META_TACTICS, SPECIAL_ABILITIES, TRAINING_GUIDE, FAQ, ABBREVIATIONS, CAREER_PATHS, MY_PLAYBOOK, SET_PIECE, BATTLE_CARDS, GAME_GUIDE, FORMATION_LAB, REAL_TACTICS, REAL_TEAMS, FORMATIONS } from '@/src/data';
import PitchDiagram from '@/src/components/PitchDiagram';

// lookup nome modulo -> posizioni, per disegnare il mini-campo nella sezione Meta
const BY_NAME: Record<string, string[]> = {};
(FORMATIONS as any[]).forEach((f) => { BY_NAME[f.name] = f.positions; });
const digitsOf = (s: string) => (s || '').replace(/\D/g, '');
function findPositions(name?: string): string[] | null {
  if (!name) return null;
  if (BY_NAME[name]) return BY_NAME[name];
  // fallback: stessa sequenza numerica (es. "4-4-2" -> "4-4-2 C (Classic)")
  const d = digitsOf(name);
  const hit = (FORMATIONS as any[]).find((f) => digitsOf(f.name) === d);
  return hit ? hit.positions : null;
}

const LOCAL_DATA: Record<string, any[]> = {
  roles: PLAYER_ROLES,
  positions: POSITION_GUIDE,
  meta: META_TACTICS,
  skills: SPECIAL_ABILITIES,
  training: TRAINING_GUIDE,
  faq: FAQ,
  abbr: ABBREVIATIONS,
  paths: CAREER_PATHS,
  mystyle: MY_PLAYBOOK,
  setpiece: SET_PIECE,
  battles: BATTLE_CARDS,
  guide: GAME_GUIDE,
  lab: FORMATION_LAB,
  realtactics: REAL_TACTICS,
  teams: REAL_TEAMS,
};

type SectionId = 'roles' | 'positions' | 'meta' | 'skills' | 'training' | 'faq' | 'abbr' | 'paths' | 'mystyle' | 'setpiece' | 'battles' | 'guide' | 'lab' | 'realtactics' | 'teams';

interface SectionDef {
  id: SectionId;
  endpoint: string;
  label_en: string;
  label_it: string;
  icon: string;
}

const SECTIONS: SectionDef[] = [
  { id: 'roles', endpoint: '/api/player-roles', label_en: 'Roles', label_it: 'Ruoli', icon: 'person-outline' },
  { id: 'positions', endpoint: '/api/position-guide', label_en: 'By Position', label_it: 'Posizioni', icon: 'body-outline' },
  { id: 'meta', endpoint: '/api/meta-tactics', label_en: 'Meta', label_it: 'Meta', icon: 'trophy-outline' },
  { id: 'skills', endpoint: '/api/special-abilities', label_en: 'Skills', label_it: 'Abilità', icon: 'flash-outline' },
  { id: 'training', endpoint: '/api/training-guide', label_en: 'Training', label_it: 'Allenam.', icon: 'barbell-outline' },
  { id: 'faq', endpoint: '/api/faq', label_en: 'FAQ', label_it: 'FAQ', icon: 'help-circle-outline' },
  { id: 'abbr', endpoint: '/api/abbreviations', label_en: 'Legend', label_it: 'Leggenda', icon: 'list-outline' },
  { id: 'paths', endpoint: '/api/career-paths', label_en: 'Paths', label_it: 'Percorsi', icon: 'trending-up-outline' },
  { id: 'mystyle', endpoint: '/api/my-playbook', label_en: 'My Style', label_it: 'Mio Stile', icon: 'compass-outline' },
  { id: 'setpiece', endpoint: '/api/set-piece', label_en: 'Set Piece', label_it: 'Piazzati', icon: 'football-outline' },
  { id: 'battles', endpoint: '/api/battle-cards', label_en: 'Battles', label_it: 'Scontri', icon: 'shuffle-outline' },
  { id: 'guide', endpoint: '/api/game-guide', label_en: 'Club Guide', label_it: 'Gestione', icon: 'briefcase-outline' },
  { id: 'lab', endpoint: '/api/formation-lab', label_en: 'Formation Lab', label_it: 'Lab Moduli', icon: 'flask-outline' },
  { id: 'realtactics', endpoint: '/api/real-tactics', label_en: 'Real Football', label_it: 'Calcio Reale', icon: 'earth-outline' },
  { id: 'teams', endpoint: '/api/real-teams', label_en: 'Team Models', label_it: 'Squadre modello', icon: 'shirt-outline' },
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

  const [section, setSection] = useState<SectionId>('meta');
  const [search, setSearch] = useState('');
  const [data, setData] = useState<Record<SectionId, any[]>>({
    roles: [], positions: [], meta: [], skills: [], training: [], faq: [], abbr: [], paths: [], mystyle: [], setpiece: [], battles: [], guide: [], lab: [], realtactics: [], teams: [],
  });
  const [loaded, setLoaded] = useState<Record<SectionId, boolean>>({
    roles: false, positions: false, meta: false, skills: false, training: false, faq: false, abbr: false, paths: false, mystyle: false, setpiece: false, battles: false, guide: false, lab: false, realtactics: false, teams: false,
  });
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
  }, [fadeAnim, modalVisible]);

  const openItem = (item: any) => {
    setSelected(item);
    setModalVisible(true);
  };

  // --- Card title/subtitle per section ---
  const cardTitle = (item: any): string => {
    switch (section) {
      case 'roles': return isIt ? item.name_it : item.name_en;
      case 'positions': return isIt ? item.name_it : item.name_en;
      case 'meta': return item.formation;
      case 'skills': return isIt ? item.name_it : item.name_en;
      case 'training': return item.position;
      case 'faq': return isIt ? item.question_it : item.question_en;
      case 'abbr': return `${item.code}  ·  ${isIt ? item.name_it : item.name_en}`;
      case 'paths': return `${item.label}  ·  ${isIt ? item.title_it : item.title_en}`;
      case 'mystyle': return `${item.order}. ${isIt ? item.category_it : item.category_en}`;
      case 'setpiece': return `${item.order}. ${isIt ? item.category_it : item.category_en}`;
      case 'battles': return isIt ? item.category_it : item.category_en;
      case 'guide': return isIt ? item.category_it : item.category_en;
      case 'lab': return item.formation;
      case 'realtactics': return `${item.team}  ·  ${item.main_formation}`;
      case 'teams': return `${item.team}  ·  ${item.te_formation}`;
      default: return '';
    }
  };
  const cardSubtitle = (item: any): string => {
    switch (section) {
      case 'roles': return item.position;
      case 'positions': return `${item.roles.length} ${isIt ? 'ruoli' : 'roles'}`;
      case 'meta': return `TIER ${item.tier}` + (item.trending ? (isIt ? ' · DI MODA' : ' · TRENDING') : '');
      case 'skills': return item.best_role;
      case 'training': return (isIt ? item.priority_attributes_it : item.priority_attributes_en).join(' · ');
      case 'faq': return (item.category || '').toUpperCase();
      case 'abbr': return item.example;
      case 'paths': return isIt ? item.subtitle_it : item.subtitle_en;
      case 'mystyle': return isIt ? item.summary_it : item.summary_en;
      case 'setpiece': return isIt ? item.summary_it : item.summary_en;
      case 'battles': return isIt ? item.summary_it : item.summary_en;
      case 'guide': return isIt ? item.summary_it : item.summary_en;
      case 'lab': return isIt ? item.style_it : item.style_en;
      case 'realtactics': return `${item.league} ${item.season} · ${item.record}`;
      case 'teams': return `${item.manager} · ${item.mentality}`;
      default: return '';
    }
  };

  const allItems = data[section];
  const q = search.trim().toLowerCase();
  const items = q
    ? allItems.filter((item) => `${cardTitle(item)} ${cardSubtitle(item)}`.toLowerCase().includes(q))
    : allItems;

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>ACADEMY</Text>
        <Text style={styles.headerSubtitle}>2026</Text>
      </View>

      <View style={styles.divider} />

      {/* Section selector: tutte le 14 sezioni in un solo livello, niente doppio menu */}
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
            onPress={() => {
              setSection(s.id);
              setSearch('');
            }}
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

      {/* Search */}
      <View style={styles.searchRow}>
        <Ionicons name="search" size={16} color={NothingTheme.colors.textTertiary} />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder={isIt ? 'Cerca in questa sezione' : 'Search this section'}
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

      {/* Count */}
      <View style={styles.countRow}>
        <Text style={styles.countText}>
          {items.length} {isIt ? 'ELEMENTI' : 'ITEMS'}
        </Text>
      </View>

      {/* List */}
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

        {items.length === 0 && (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>{isIt ? 'Nessun dato disponibile' : 'No data available'}</Text>
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
              {selected && section === 'positions' && (
                <>
                  <DetailBlock label={isIt ? 'COME USARLA' : 'HOW TO USE'} value={isIt ? selected.summary_it : selected.summary_en} />
                  {(selected.roles || []).map((r: any, i: number) => (
                    <View key={i} style={styles.detailBlock}>
                      <Text style={styles.detailLabel}>{`${i + 1}. ${(isIt ? r.name_it : r.name_en).toUpperCase()}`}</Text>
                      <View style={styles.chipRow}>
                        {(isIt ? r.key_attributes_it : r.key_attributes_en).map((a: string, j: number) => (
                          <View key={`a${j}`} style={styles.chip}><Text style={styles.chipText}>{a}</Text></View>
                        ))}
                      </View>
                      <View style={[styles.chipRow, { marginTop: 6 }]}>
                        {(r.best_formations || []).map((f: string, j: number) => (
                          <View key={`f${j}`} style={styles.chip}><Text style={styles.chipText}>{f}</Text></View>
                        ))}
                      </View>
                    </View>
                  ))}
                </>
              )}
              {selected && section === 'meta' && (
                <>
                  {findPositions(selected.formation) && (
                    <View style={styles.pitchBlock}>
                      <PitchDiagram positions={findPositions(selected.formation)!} />
                    </View>
                  )}
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
              {selected && section === 'faq' && (
                <>
                  <DetailBlock label={isIt ? 'RISPOSTA' : 'ANSWER'} value={isIt ? selected.answer_it : selected.answer_en} />
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
              {selected && (section === 'mystyle' || section === 'setpiece' || section === 'battles' || section === 'guide') && (
                <>
                  <DetailBlock label={isIt ? 'SINTESI' : 'SUMMARY'} value={isIt ? selected.summary_it : selected.summary_en} />
                  {((isIt ? selected.bullets_it : selected.bullets_en) || []).length > 0 && (
                    <DetailChips label={isIt ? 'PUNTI CHIAVE' : 'KEY POINTS'} values={isIt ? selected.bullets_it : selected.bullets_en} />
                  )}
                  {(isIt ? selected.table_it : selected.table_en) && (
                    <DetailTable label={isIt ? 'DETTAGLI' : 'DETAILS'} rows={isIt ? selected.table_it : selected.table_en} />
                  )}
                  {(isIt ? selected.source_it : selected.source_en) && (
                    <DetailBlock label={isIt ? 'FONTE' : 'SOURCE'} value={isIt ? selected.source_it : selected.source_en} />
                  )}
                </>
              )}
              {selected && section === 'realtactics' && (
                <>
                  {findPositions(selected.te_formation) && (
                    <View style={styles.pitchBlock}>
                      <PitchDiagram positions={findPositions(selected.te_formation)!} />
                    </View>
                  )}
                  <DetailBlock
                    label={isIt ? 'MODULO PIÙ USATO' : 'MOST USED FORMATION'}
                    value={`${selected.main_formation} — ${selected.main_played}/${selected.matches} ${isIt ? 'partite' : 'matches'}`}
                  />
                  {(selected.alternates || []).length > 0 && (
                    <DetailChips label={isIt ? 'ALTERNATIVE USATE' : 'ALTERNATIVES USED'} values={selected.alternates} />
                  )}
                  <DetailTable
                    label={isIt ? 'STAGIONE' : 'SEASON'}
                    rows={[
                      { label: isIt ? 'Bilancio' : 'Record', value: selected.record },
                      { label: isIt ? 'Gol fatti' : 'Goals for', value: String(selected.goals_for) },
                      { label: isIt ? 'Gol subiti' : 'Goals against', value: String(selected.goals_against) },
                      { label: isIt ? 'Porta inviolata' : 'Clean sheets', value: String(selected.clean_sheets) },
                    ]}
                  />
                  <DetailBlock label={isIt ? 'COSA IMPARARNE' : 'WHAT TO LEARN'} value={isIt ? selected.lesson_it : selected.lesson_en} />
                  <DetailBlock label={isIt ? 'MODULO EQUIVALENTE IN TOP ELEVEN' : 'TOP ELEVEN EQUIVALENT'} value={selected.te_formation} />
                  <DetailBlock label={isIt ? 'FONTE' : 'SOURCE'} value={isIt ? selected.source_it : selected.source_en} />
                </>
              )}
              {selected && section === 'teams' && (
                <>
                  {findPositions(selected.te_formation) && (
                    <View style={styles.pitchBlock}>
                      <PitchDiagram positions={findPositions(selected.te_formation)!} />
                    </View>
                  )}
                  <DetailBlock label={isIt ? 'STILE' : 'STYLE'} value={isIt ? selected.style_it : selected.style_en} />
                  <DetailChips label={isIt ? 'ATTRIBUTI CHIAVE' : 'KEY ATTRIBUTES'} values={isIt ? selected.key_attributes_it : selected.key_attributes_en} />
                  <DetailBlock label={isIt ? 'FRECCE E MENTALITÀ' : 'ARROWS AND MENTALITY'} value={`${selected.arrows} · ${selected.mentality}`} />
                  <DetailBlock label={isIt ? 'FILOSOFIA' : 'PHILOSOPHY'} value={isIt ? selected.philosophy_it : selected.philosophy_en} />
                  <DetailBlock label={isIt ? 'CONFIGURAZIONE BASE' : 'BASE SETUP'} value={isIt ? selected.how_to_copy_it : selected.how_to_copy_en} />
                  {(selected.variants || []).map((variant: any) => (
                    <View key={variant.id} style={styles.detailBlock}>
                      <Text style={styles.detailLabel}>{isIt ? variant.name_it.toUpperCase() : variant.name_en.toUpperCase()}</Text>
                      <DetailBlock label={isIt ? 'SETUP' : 'SETUP'} value={isIt ? variant.setup_it : variant.setup_en} />
                      <DetailBlock label={isIt ? 'QUANDO USARLA' : 'WHEN TO USE'} value={isIt ? variant.when_to_use_it : variant.when_to_use_en} />
                      <DetailBlock label={isIt ? 'RISCHIO PRINCIPALE' : 'MAIN RISK'} value={isIt ? variant.risk_it : variant.risk_en} />
                    </View>
                  ))}
                </>
              )}
              {selected && section === 'lab' && (
                <>
                  <View style={styles.pitchBlock}>
                    <PitchDiagram positions={selected.positions} />
                  </View>
                  <DetailBlock label={isIt ? 'IDENTITÀ TATTICA' : 'TACTICAL IDENTITY'} value={isIt ? selected.style_it : selected.style_en} />
                  <DetailBlock label={isIt ? 'QUANDO PROVARLA' : 'WHEN TO TRY IT'} value={isIt ? selected.use_it : selected.use_en} />
                  <DetailBlock label={isIt ? 'RISCHIO PRINCIPALE' : 'MAIN RISK'} value={isIt ? selected.risk_it : selected.risk_en} />
                  <DetailBlock label={isIt ? 'FONTE E STATO' : 'SOURCE AND STATUS'} value={isIt ? selected.source_it : selected.source_en} />
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
  pitchBlock: { marginBottom: 24, marginTop: 4 },
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
