import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { FORMATIONS } from '@/src/data';
import PitchDiagram from './PitchDiagram';

interface Props {
  visible: boolean;
  onClose: () => void;
}

type Slot = 'a' | 'b' | null;

/** Confronto diretto tra due moduli: chi è favorito secondo il reverse-lookup. */
export default function CompareModal({ visible, onClose }: Props) {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const isIt = language === 'it';
  const [a, setA] = useState<any | null>(null);
  const [b, setB] = useState<any | null>(null);
  const [picking, setPicking] = useState<Slot>(null);
  const [search, setSearch] = useState('');

  const close = () => { setA(null); setB(null); setPicking(null); setSearch(''); onClose(); };

  const qDigits = search.replace(/\D/g, '');
  const list = useMemo(() => {
    const all = FORMATIONS as any[];
    if (!search.trim()) return all;
    return all.filter((f) =>
      f.name.toLowerCase().includes(search.toLowerCase().trim()) ||
      (qDigits.length > 0 && f.name.replace(/\D/g, '').includes(qDigits))
    );
  }, [search, qDigits]);

  const pick = (f: any) => {
    if (picking === 'a') setA(f); else if (picking === 'b') setB(f);
    setPicking(null); setSearch('');
  };

  // verdetto dal reverse-lookup: chi batte chi
  const verdict = useMemo(() => {
    if (!a || !b) return null;
    const aBeatsB = (a.effective_against || []).includes(b.name) || (b.vulnerable_to || []).includes(a.name);
    const bBeatsA = (b.effective_against || []).includes(a.name) || (a.vulnerable_to || []).includes(b.name);
    if (aBeatsB && !bBeatsA) return { winner: 'a', text: isIt ? `${a.name} è favorito` : `${a.name} is favoured` };
    if (bBeatsA && !aBeatsB) return { winner: 'b', text: isIt ? `${b.name} è favorito` : `${b.name} is favoured` };
    return { winner: 'even', text: isIt ? 'Equilibrato: nessun vantaggio netto' : 'Even: no clear advantage' };
  }, [a, b, isIt]);

  const Slot = ({ side, f }: { side: 'a' | 'b'; f: any | null }) => (
    <TouchableOpacity style={styles.slot} onPress={() => { setPicking(side); setSearch(''); }} activeOpacity={0.8}>
      <Text style={styles.slotLabel}>{side === 'a' ? 'A' : 'B'}</Text>
      {f ? (
        <>
          <PitchDiagram positions={f.positions} height={170} />
          <Text style={styles.slotName} numberOfLines={1}>{f.name}</Text>
        </>
      ) : (
        <View style={styles.slotEmpty}>
          <Ionicons name="add" size={28} color={NothingTheme.colors.textTertiary} />
          <Text style={styles.slotEmptyText}>{isIt ? 'Scegli' : 'Pick'}</Text>
        </View>
      )}
    </TouchableOpacity>
  );

  return (
    <Modal animationType="slide" transparent visible={visible} onRequestClose={close}>
      <View style={[styles.overlay, { paddingTop: insets.top + 10 }]}>
        <View style={styles.header}>
          {picking && (
            <TouchableOpacity style={styles.iconBtn} onPress={() => setPicking(null)}>
              <Ionicons name="arrow-back" size={22} color={NothingTheme.colors.textPrimary} />
            </TouchableOpacity>
          )}
          <Text style={styles.title}>{isIt ? 'CONFRONTO' : 'COMPARE'}</Text>
          <TouchableOpacity style={[styles.iconBtn, styles.iconBtnRight]} onPress={close}>
            <Ionicons name="close" size={24} color={NothingTheme.colors.textPrimary} />
          </TouchableOpacity>
        </View>
        <View style={styles.divider} />

        {picking ? (
          <>
            <View style={styles.searchRow}>
              <Ionicons name="search" size={16} color={NothingTheme.colors.textTertiary} />
              <TextInput
                style={styles.searchInput}
                value={search}
                onChangeText={setSearch}
                placeholder={isIt ? `Modulo ${picking.toUpperCase()} (es. 4-3-3)` : `Formation ${picking.toUpperCase()} (e.g. 4-3-3)`}
                placeholderTextColor={NothingTheme.colors.textTertiary}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>
            <ScrollView contentContainerStyle={styles.listPad} showsVerticalScrollIndicator={false}>
              {list.map((f, i) => (
                <TouchableOpacity key={i} style={styles.row} onPress={() => pick(f)} activeOpacity={0.7}>
                  <Text style={styles.rowText}>{f.name}</Text>
                  <Ionicons name="chevron-forward" size={18} color={NothingTheme.colors.textTertiary} />
                </TouchableOpacity>
              ))}
            </ScrollView>
          </>
        ) : (
          <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
            <View style={styles.slots}>
              <Slot side="a" f={a} />
              <Text style={styles.vs}>VS</Text>
              <Slot side="b" f={b} />
            </View>
            {verdict && (
              <View style={[
                styles.verdict,
                verdict.winner === 'even' ? styles.verdictEven : styles.verdictWin,
              ]}>
                <Ionicons
                  name={verdict.winner === 'even' ? 'swap-horizontal' : 'trophy'}
                  size={20}
                  color={verdict.winner === 'even' ? NothingTheme.colors.textSecondary : NothingTheme.colors.accent}
                />
                <Text style={styles.verdictText}>{verdict.text}</Text>
              </View>
            )}
            {a && b && verdict?.winner !== 'even' && (
              <Text style={styles.hint}>
                {isIt
                  ? 'Basato sui match-up verificati. Conta anche il livello rosa e le impostazioni.'
                  : 'Based on verified match-ups. Squad level and settings also matter.'}
              </Text>
            )}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: NothingTheme.colors.background },
  header: { paddingHorizontal: 24, paddingBottom: 16, alignItems: 'center', justifyContent: 'center' },
  title: { color: NothingTheme.colors.textPrimary, fontSize: 18, fontWeight: '700', letterSpacing: 2 },
  iconBtn: { position: 'absolute', left: 24, top: -4, width: 40, height: 40, borderRadius: 20, backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border, alignItems: 'center', justifyContent: 'center', zIndex: 1 },
  iconBtnRight: { left: undefined, right: 24 },
  divider: { height: 1, backgroundColor: NothingTheme.colors.divider },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 24, marginTop: 16, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border },
  searchInput: { flex: 1, color: NothingTheme.colors.textPrimary, fontSize: 14, padding: 0 },
  listPad: { padding: 24, paddingTop: 12, paddingBottom: 60 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: NothingTheme.colors.surface, borderRadius: 8, padding: 16, marginBottom: 8, borderWidth: 1, borderColor: NothingTheme.colors.border },
  rowText: { color: NothingTheme.colors.textPrimary, fontSize: 15, fontWeight: '600' },
  body: { padding: 24, paddingBottom: 60 },
  slots: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  slot: { flex: 1, backgroundColor: NothingTheme.colors.surface, borderRadius: 10, padding: 10, borderWidth: 1, borderColor: NothingTheme.colors.border },
  slotLabel: { color: NothingTheme.colors.textTertiary, fontSize: 11, fontWeight: '700', letterSpacing: 1, marginBottom: 8 },
  slotName: { color: NothingTheme.colors.textPrimary, fontSize: 13, fontWeight: '700', textAlign: 'center', marginTop: 8 },
  slotEmpty: { height: 170, alignItems: 'center', justifyContent: 'center' },
  slotEmptyText: { color: NothingTheme.colors.textTertiary, fontSize: 12, marginTop: 4 },
  vs: { color: NothingTheme.colors.accent, fontSize: 14, fontWeight: '700', letterSpacing: 1 },
  verdict: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 20, padding: 16, borderRadius: 10, borderWidth: 1 },
  verdictWin: { backgroundColor: NothingTheme.colors.accentMuted, borderColor: NothingTheme.colors.accent },
  verdictEven: { backgroundColor: NothingTheme.colors.surface, borderColor: NothingTheme.colors.border },
  verdictText: { flex: 1, color: NothingTheme.colors.textPrimary, fontSize: 14, fontWeight: '600' },
  hint: { color: NothingTheme.colors.textTertiary, fontSize: 11, lineHeight: 16, marginTop: 12 },
});
