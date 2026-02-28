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
import { useAuth } from '@/src/context/AuthContext';
import axios from 'axios';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface OpponentSettings {
  mentality: string;
  mentality_it: string;
  focus_passing: string;
  focus_passing_it: string;
  passing_style: string;
  passing_style_it: string;
  counter_attack: boolean;
  pressing: string;
  pressing_it: string;
  tackling: string;
  tackling_it: string;
  marking: string;
  marking_it: string;
  offside_trap: boolean;
  tip_en: string;
  tip_it: string;
}

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
  recommended_tactics?: {
    mentality: string;
    focus_passing: string;
    passing_style: string;
    counter_attack: boolean;
    pressing: string;
    tackling: string;
    marking: string;
    offside_trap: boolean;
  };
  opponent_settings?: {
    strong: OpponentSettings;
    equal: OpponentSettings;
    weak: OpponentSettings;
  };
}

export default function FormationsScreen() {
  const insets = useSafeAreaInsets();
  const { t, language } = useLanguage();
  const { sessionToken, isAuthenticated } = useAuth();
  const [formations, setFormations] = useState<Formation[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedFormation, setSelectedFormation] = useState<Formation | null>(null);
  const [selectedOpponentLevel, setSelectedOpponentLevel] = useState<'strong' | 'equal' | 'weak'>('equal');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [formationsRes, favoritesRes] = await Promise.all([
        axios.get(`${API_URL}/api/formations`),
        isAuthenticated
          ? axios.get(`${API_URL}/api/favorites`, {
              headers: { Authorization: `Bearer ${sessionToken}` },
            })
          : Promise.resolve({ data: [] }),
      ]);

      setFormations(formationsRes.data);
      setFavorites(favoritesRes.data.map((f: any) => f.formation_id));
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
    }
  };

  const toggleFavorite = async (formationId: string) => {
    if (!isAuthenticated) return;

    try {
      if (favorites.includes(formationId)) {
        await axios.delete(`${API_URL}/api/favorites/${formationId}`, {
          headers: { Authorization: `Bearer ${sessionToken}` },
        });
        setFavorites(favorites.filter((f) => f !== formationId));
      } else {
        await axios.post(`${API_URL}/api/favorites?formation_id=${formationId}`, {}, {
          headers: { Authorization: `Bearer ${sessionToken}` },
        });
        setFavorites([...favorites, formationId]);
      }
    } catch (error) {
      console.error('Error toggling favorite:', error);
    }
  };

  const renderFormationPitch = (positions: string[]) => {
    // Simplified pitch visualization
    return (
      <View style={styles.pitch}>
        <View style={styles.pitchLines}>
          <View style={styles.centerCircle} />
          <View style={styles.centerLine} />
        </View>
        <View style={styles.positionsContainer}>
          {positions.map((pos, index) => (
            <View
              key={index}
              style={[
                styles.positionDot,
                getPositionStyle(pos, index, positions.length),
              ]}
            >
              <Text style={styles.positionText}>{pos}</Text>
            </View>
          ))}
        </View>
      </View>
    );
  };

  const getPositionStyle = (position: string, index: number, total: number) => {
    // Simplified positioning based on common patterns
    const row = Math.floor(index / 4);
    const col = index % 4;
    return {
      left: `${20 + col * 20}%`,
      top: `${10 + row * 25}%`,
    };
  };

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
        <Text style={styles.headerTitle}>{t('allFormations')}</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.grid}>
          {formations.map((formation) => (
            <TouchableOpacity
              key={formation.id}
              style={styles.formationCard}
              onPress={() => setSelectedFormation(formation)}
            >
              <View style={styles.cardHeader}>
                <Text style={styles.formationName}>{formation.name}</Text>
                {isAuthenticated && (
                  <TouchableOpacity
                    onPress={() => toggleFavorite(formation.id)}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                  >
                    <Ionicons
                      name={favorites.includes(formation.id) ? 'heart' : 'heart-outline'}
                      size={24}
                      color={favorites.includes(formation.id) ? '#ef4444' : 'rgba(255,255,255,0.5)'}
                    />
                  </TouchableOpacity>
                )}
              </View>
              <Text style={styles.formationDescription} numberOfLines={2}>
                {language === 'it' ? formation.description_it : formation.description_en}
              </Text>
              <View style={styles.cardFooter}>
                <Ionicons name="eye-outline" size={16} color="#10b981" />
                <Text style={styles.cardFooterText}>
                  {language === 'it' ? 'Vedi dettagli' : 'View details'}
                </Text>
              </View>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>

      {/* Formation Detail Modal */}
      <Modal
        visible={!!selectedFormation}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setSelectedFormation(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { paddingBottom: insets.bottom + 20 }]}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>{selectedFormation?.name}</Text>
              <TouchableOpacity onPress={() => setSelectedFormation(null)}>
                <Ionicons name="close" size={28} color="#fff" />
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalScroll}>
              <Text style={styles.modalDescription}>
                {language === 'it'
                  ? selectedFormation?.description_it
                  : selectedFormation?.description_en}
              </Text>

              {/* Tactic Type Badge */}
              {selectedFormation?.tactic_type_en && (
                <View style={styles.tacticTypeBadge}>
                  <Ionicons name="football" size={16} color="#fff" />
                  <Text style={styles.tacticTypeText}>
                    {language === 'it' 
                      ? selectedFormation.tactic_type_it 
                      : selectedFormation.tactic_type_en}
                  </Text>
                </View>
              )}

              <View style={styles.modalSection}>
                <View style={styles.sectionHeader}>
                  <Ionicons name="checkmark-circle" size={20} color="#10b981" />
                  <Text style={styles.sectionTitle}>{t('strengths')}</Text>
                </View>
                {(language === 'it'
                  ? selectedFormation?.strengths_it
                  : selectedFormation?.strengths_en
                )?.map((strength, index) => (
                  <View key={index} style={styles.listItem}>
                    <Text style={styles.bullet}>•</Text>
                    <Text style={styles.listText}>{strength}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.modalSection}>
                <View style={styles.sectionHeader}>
                  <Ionicons name="warning" size={20} color="#f59e0b" />
                  <Text style={styles.sectionTitle}>{t('weaknesses')}</Text>
                </View>
                {(language === 'it'
                  ? selectedFormation?.weaknesses_it
                  : selectedFormation?.weaknesses_en
                )?.map((weakness, index) => (
                  <View key={index} style={styles.listItem}>
                    <Text style={styles.bullet}>•</Text>
                    <Text style={styles.listText}>{weakness}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.modalSection}>
                <View style={styles.sectionHeader}>
                  <Ionicons name="people" size={20} color="#3b82f6" />
                  <Text style={styles.sectionTitle}>{t('positions')}</Text>
                </View>
                <View style={styles.positionsList}>
                  {selectedFormation?.positions.map((pos, index) => (
                    <View key={index} style={styles.positionBadge}>
                      <Text style={styles.positionBadgeText}>{pos}</Text>
                    </View>
                  ))}
                </View>
              </View>

              {/* Opponent Level Selector */}
              {selectedFormation?.opponent_settings && (
                <View style={styles.modalSection}>
                  <View style={styles.sectionHeader}>
                    <Ionicons name="game-controller" size={20} color="#8b5cf6" />
                    <Text style={styles.sectionTitle}>
                      {language === 'it' ? 'Tattiche per Avversario' : 'Tactics by Opponent'}
                    </Text>
                  </View>
                  
                  {/* Opponent Level Tabs */}
                  <View style={styles.opponentTabs}>
                    <TouchableOpacity
                      style={[
                        styles.opponentTab,
                        selectedOpponentLevel === 'strong' && styles.opponentTabActive,
                        selectedOpponentLevel === 'strong' && styles.opponentTabStrong,
                      ]}
                      onPress={() => setSelectedOpponentLevel('strong')}
                    >
                      <Ionicons 
                        name="arrow-up-circle" 
                        size={18} 
                        color={selectedOpponentLevel === 'strong' ? '#fff' : '#ef4444'} 
                      />
                      <Text style={[
                        styles.opponentTabText,
                        selectedOpponentLevel === 'strong' && styles.opponentTabTextActive,
                      ]}>
                        {language === 'it' ? 'Forte' : 'Strong'}
                      </Text>
                    </TouchableOpacity>
                    
                    <TouchableOpacity
                      style={[
                        styles.opponentTab,
                        selectedOpponentLevel === 'equal' && styles.opponentTabActive,
                        selectedOpponentLevel === 'equal' && styles.opponentTabEqual,
                      ]}
                      onPress={() => setSelectedOpponentLevel('equal')}
                    >
                      <Ionicons 
                        name="remove-circle" 
                        size={18} 
                        color={selectedOpponentLevel === 'equal' ? '#fff' : '#f59e0b'} 
                      />
                      <Text style={[
                        styles.opponentTabText,
                        selectedOpponentLevel === 'equal' && styles.opponentTabTextActive,
                      ]}>
                        {language === 'it' ? 'Pari' : 'Equal'}
                      </Text>
                    </TouchableOpacity>
                    
                    <TouchableOpacity
                      style={[
                        styles.opponentTab,
                        selectedOpponentLevel === 'weak' && styles.opponentTabActive,
                        selectedOpponentLevel === 'weak' && styles.opponentTabWeak,
                      ]}
                      onPress={() => setSelectedOpponentLevel('weak')}
                    >
                      <Ionicons 
                        name="arrow-down-circle" 
                        size={18} 
                        color={selectedOpponentLevel === 'weak' ? '#fff' : '#10b981'} 
                      />
                      <Text style={[
                        styles.opponentTabText,
                        selectedOpponentLevel === 'weak' && styles.opponentTabTextActive,
                      ]}>
                        {language === 'it' ? 'Debole' : 'Weak'}
                      </Text>
                    </TouchableOpacity>
                  </View>

                  {/* Tactical Settings for Selected Opponent Level */}
                  {selectedFormation.opponent_settings[selectedOpponentLevel] && (
                    <View style={styles.tacticsContainer}>
                      {/* Tip */}
                      <View style={styles.tipBox}>
                        <Ionicons name="bulb" size={18} color="#f59e0b" />
                        <Text style={styles.tipText}>
                          {language === 'it' 
                            ? selectedFormation.opponent_settings[selectedOpponentLevel].tip_it
                            : selectedFormation.opponent_settings[selectedOpponentLevel].tip_en}
                        </Text>
                      </View>

                      {/* Tactical Settings Grid */}
                      <View style={styles.tacticsGrid}>
                        <View style={styles.tacticItem}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? 'Mentalità' : 'Mentality'}
                          </Text>
                          <Text style={styles.tacticValue}>
                            {language === 'it' 
                              ? selectedFormation.opponent_settings[selectedOpponentLevel].mentality_it
                              : selectedFormation.opponent_settings[selectedOpponentLevel].mentality}
                          </Text>
                        </View>
                        
                        <View style={styles.tacticItem}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? 'Focus Pass.' : 'Pass Focus'}
                          </Text>
                          <Text style={styles.tacticValue}>
                            {language === 'it' 
                              ? selectedFormation.opponent_settings[selectedOpponentLevel].focus_passing_it
                              : selectedFormation.opponent_settings[selectedOpponentLevel].focus_passing}
                          </Text>
                        </View>
                        
                        <View style={styles.tacticItem}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? 'Stile Pass.' : 'Pass Style'}
                          </Text>
                          <Text style={styles.tacticValue}>
                            {language === 'it' 
                              ? selectedFormation.opponent_settings[selectedOpponentLevel].passing_style_it
                              : selectedFormation.opponent_settings[selectedOpponentLevel].passing_style}
                          </Text>
                        </View>
                        
                        <View style={styles.tacticItem}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? 'Pressing' : 'Pressing'}
                          </Text>
                          <Text style={styles.tacticValue}>
                            {language === 'it' 
                              ? selectedFormation.opponent_settings[selectedOpponentLevel].pressing_it
                              : selectedFormation.opponent_settings[selectedOpponentLevel].pressing}
                          </Text>
                        </View>
                        
                        <View style={styles.tacticItem}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? 'Contrasti' : 'Tackling'}
                          </Text>
                          <Text style={styles.tacticValue}>
                            {language === 'it' 
                              ? selectedFormation.opponent_settings[selectedOpponentLevel].tackling_it
                              : selectedFormation.opponent_settings[selectedOpponentLevel].tackling}
                          </Text>
                        </View>
                        
                        <View style={styles.tacticItem}>
                          <Text style={styles.tacticLabel}>
                            {language === 'it' ? 'Marcatura' : 'Marking'}
                          </Text>
                          <Text style={styles.tacticValue}>
                            {language === 'it' 
                              ? selectedFormation.opponent_settings[selectedOpponentLevel].marking_it
                              : selectedFormation.opponent_settings[selectedOpponentLevel].marking}
                          </Text>
                        </View>
                      </View>

                      {/* Toggle Settings */}
                      <View style={styles.togglesContainer}>
                        <View style={styles.toggleItem}>
                          <Text style={styles.toggleLabel}>
                            {language === 'it' ? 'Contropiede' : 'Counter-Attack'}
                          </Text>
                          <View style={[
                            styles.toggleBadge,
                            selectedFormation.opponent_settings[selectedOpponentLevel].counter_attack 
                              ? styles.toggleOn 
                              : styles.toggleOff
                          ]}>
                            <Text style={styles.toggleText}>
                              {selectedFormation.opponent_settings[selectedOpponentLevel].counter_attack 
                                ? (language === 'it' ? 'SÌ' : 'ON')
                                : (language === 'it' ? 'NO' : 'OFF')}
                            </Text>
                          </View>
                        </View>
                        
                        <View style={styles.toggleItem}>
                          <Text style={styles.toggleLabel}>
                            {language === 'it' ? 'Fuorigioco' : 'Offside Trap'}
                          </Text>
                          <View style={[
                            styles.toggleBadge,
                            selectedFormation.opponent_settings[selectedOpponentLevel].offside_trap 
                              ? styles.toggleOn 
                              : styles.toggleOff
                          ]}>
                            <Text style={styles.toggleText}>
                              {selectedFormation.opponent_settings[selectedOpponentLevel].offside_trap 
                                ? (language === 'it' ? 'SÌ' : 'ON')
                                : (language === 'it' ? 'NO' : 'OFF')}
                            </Text>
                          </View>
                        </View>
                      </View>
                    </View>
                  )}
                </View>
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
    paddingBottom: 16,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingTop: 0,
    paddingBottom: 100,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  formationCard: {
    width: '48%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  formationName: {
    color: '#10b981',
    fontSize: 24,
    fontWeight: 'bold',
  },
  formationDescription: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 12,
    lineHeight: 18,
    marginBottom: 12,
  },
  cardFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  cardFooterText: {
    color: '#10b981',
    fontSize: 12,
    fontWeight: '500',
  },
  pitch: {
    height: 150,
    backgroundColor: '#1a472a',
    borderRadius: 8,
    marginVertical: 12,
    overflow: 'hidden',
  },
  pitchLines: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  centerCircle: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
  },
  centerLine: {
    position: 'absolute',
    width: '100%',
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.3)',
  },
  positionsContainer: {
    flex: 1,
    position: 'relative',
  },
  positionDot: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#10b981',
    alignItems: 'center',
    justifyContent: 'center',
  },
  positionText: {
    color: '#fff',
    fontSize: 8,
    fontWeight: 'bold',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.8)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: '#0a0f1a',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: '85%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  modalTitle: {
    color: '#10b981',
    fontSize: 32,
    fontWeight: 'bold',
  },
  modalScroll: {
    padding: 20,
  },
  modalDescription: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 15,
    lineHeight: 24,
    marginBottom: 24,
  },
  modalSection: {
    marginBottom: 24,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 12,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
  listItem: {
    flexDirection: 'row',
    marginBottom: 8,
    paddingLeft: 8,
  },
  bullet: {
    color: '#10b981',
    fontSize: 14,
    marginRight: 8,
  },
  listText: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 14,
    flex: 1,
  },
  positionsList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  positionBadge: {
    backgroundColor: 'rgba(16,185,129,0.2)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  positionBadgeText: {
    color: '#10b981',
    fontSize: 13,
    fontWeight: '600',
  },
  tacticTypeBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(139,92,246,0.2)',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 12,
    marginBottom: 20,
    alignSelf: 'flex-start',
    gap: 8,
    borderWidth: 1,
    borderColor: 'rgba(139,92,246,0.3)',
  },
  tacticTypeText: {
    color: '#a78bfa',
    fontSize: 14,
    fontWeight: '600',
  },
  opponentTabs: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
  },
  opponentTab: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    gap: 6,
  },
  opponentTabActive: {
    borderWidth: 0,
  },
  opponentTabStrong: {
    backgroundColor: '#ef4444',
  },
  opponentTabEqual: {
    backgroundColor: '#f59e0b',
  },
  opponentTabWeak: {
    backgroundColor: '#10b981',
  },
  opponentTabText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 13,
    fontWeight: '600',
  },
  opponentTabTextActive: {
    color: '#fff',
  },
  tacticsContainer: {
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  tipBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: 'rgba(245,158,11,0.1)',
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    gap: 10,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.2)',
  },
  tipText: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 13,
    lineHeight: 20,
    flex: 1,
  },
  tacticsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 16,
  },
  tacticItem: {
    width: '48%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 10,
    padding: 12,
  },
  tacticLabel: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 11,
    marginBottom: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  tacticValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  togglesContainer: {
    flexDirection: 'row',
    gap: 12,
  },
  toggleItem: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 10,
    padding: 12,
  },
  toggleLabel: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 12,
    fontWeight: '500',
  },
  toggleBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
  },
  toggleOn: {
    backgroundColor: '#10b981',
  },
  toggleOff: {
    backgroundColor: 'rgba(255,255,255,0.2)',
  },
  toggleText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
  },
});
