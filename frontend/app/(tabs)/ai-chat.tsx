import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  Animated,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import axios from 'axios';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export default function AIChatScreen() {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollViewRef = useRef<ScrollView>(null);
  const [pulseAnim] = useState(new Animated.Value(1));

  // Pulse animation for loading
  const startPulse = () => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 0.5,
          duration: 500,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 1,
          duration: 500,
          useNativeDriver: true,
        }),
      ])
    ).start();
  };

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    startPulse();

    setTimeout(() => {
      scrollViewRef.current?.scrollToEnd({ animated: true });
    }, 100);

    try {
      const response = await axios.post(`${API_URL}/api/ai/chat`, {
        message: userMessage.content,
        language: language,
      });

      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.data.response,
        created_at: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error: any) {
      console.error('Error sending message:', error);
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: language === 'it' 
          ? 'Errore di connessione. Riprova.'
          : 'Connection error. Try again.',
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
      pulseAnim.setValue(1);
      setTimeout(() => {
        scrollViewRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  };

  const clearHistory = () => {
    setMessages([]);
  };

  const suggestions = [
    language === 'it' ? 'Come contrastare il 4-3-3?' : 'How to counter 4-3-3?',
    language === 'it' ? 'Miglior formazione META 2026' : 'Best META formation 2026',
    language === 'it' ? 'Tattica vs avversario forte' : 'Tactics vs stronger opponent',
  ];

  return (
    <KeyboardAvoidingView
      style={[styles.container, { paddingTop: insets.top }]}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={0}
    >
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <View style={styles.aiIconContainer}>
            <View style={styles.dotGrid}>
              {[...Array(4)].map((_, i) => (
                <View 
                  key={i} 
                  style={[
                    styles.dot,
                    (i === 0 || i === 3) && styles.dotActive
                  ]} 
                />
              ))}
            </View>
          </View>
          <View>
            <Text style={styles.headerTitle}>TACTICAL</Text>
            <Text style={styles.headerSubtitle}>AI</Text>
          </View>
        </View>
        {messages.length > 0 && (
          <TouchableOpacity 
            style={styles.clearButton}
            onPress={clearHistory}
          >
            <Ionicons name="trash-outline" size={20} color={NothingTheme.colors.textTertiary} />
          </TouchableOpacity>
        )}
      </View>

      <View style={styles.divider} />

      {/* Messages */}
      <ScrollView
        ref={scrollViewRef}
        style={styles.messagesContainer}
        contentContainerStyle={styles.messagesContent}
        showsVerticalScrollIndicator={false}
        onContentSizeChange={() => scrollViewRef.current?.scrollToEnd({ animated: true })}
      >
        {messages.length === 0 ? (
          <View style={styles.emptyState}>
            <View style={styles.emptyIconContainer}>
              <View style={styles.largeDotGrid}>
                {[...Array(9)].map((_, i) => (
                  <View 
                    key={i} 
                    style={[
                      styles.largeDot,
                      (i === 4) && styles.largeDotActive
                    ]} 
                  />
                ))}
              </View>
            </View>
            <Text style={styles.emptyTitle}>
              {language === 'it' ? 'Chiedi consiglio' : 'Ask for advice'}
            </Text>
            <Text style={styles.emptySubtitle}>
              {language === 'it'
                ? 'Formazioni, tattiche, giocatori...'
                : 'Formations, tactics, players...'}
            </Text>
            
            {/* Suggestions */}
            <View style={styles.suggestions}>
              {suggestions.map((suggestion, index) => (
                <TouchableOpacity 
                  key={index}
                  style={styles.suggestionChip}
                  onPress={() => setInput(suggestion)}
                >
                  <Text style={styles.suggestionText}>{suggestion}</Text>
                  <Ionicons 
                    name="arrow-forward" 
                    size={14} 
                    color={NothingTheme.colors.textTertiary} 
                  />
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ) : (
          messages.map((message) => (
            <View
              key={message.id}
              style={[
                styles.messageBubble,
                message.role === 'user' ? styles.userBubble : styles.assistantBubble,
              ]}
            >
              {message.role === 'assistant' && (
                <View style={styles.assistantDot}>
                  <View style={styles.miniDot} />
                </View>
              )}
              <Text style={[
                styles.messageText,
                message.role === 'user' && styles.userMessageText,
              ]}>
                {message.content}
              </Text>
            </View>
          ))
        )}
        
        {loading && (
          <View style={[styles.messageBubble, styles.assistantBubble]}>
            <Animated.View style={[styles.assistantDot, { opacity: pulseAnim }]}>
              <View style={[styles.miniDot, styles.miniDotActive]} />
            </Animated.View>
            <View style={styles.loadingDots}>
              <View style={styles.loadingDot} />
              <View style={[styles.loadingDot, { marginLeft: 4 }]} />
              <View style={[styles.loadingDot, { marginLeft: 4 }]} />
            </View>
          </View>
        )}
      </ScrollView>

      {/* Input */}
      <View style={[styles.inputContainer, { paddingBottom: insets.bottom + 10 }]}>
        <View style={styles.inputWrapper}>
          <TextInput
            style={styles.input}
            value={input}
            onChangeText={setInput}
            placeholder={language === 'it' ? 'Scrivi...' : 'Type...'}
            placeholderTextColor={NothingTheme.colors.textTertiary}
            multiline
            maxLength={500}
            onSubmitEditing={sendMessage}
          />
          <TouchableOpacity
            style={[
              styles.sendButton,
              (!input.trim() || loading) && styles.sendButtonDisabled
            ]}
            onPress={sendMessage}
            disabled={!input.trim() || loading}
          >
            <Ionicons 
              name="arrow-up" 
              size={20} 
              color={(!input.trim() || loading) 
                ? NothingTheme.colors.textTertiary 
                : NothingTheme.colors.background
              } 
            />
          </TouchableOpacity>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 24,
    paddingBottom: 16,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  aiIconContainer: {
    width: 44,
    height: 44,
    borderRadius: 8,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotGrid: {
    width: 20,
    height: 20,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.dotInactive,
  },
  dotActive: {
    backgroundColor: NothingTheme.colors.dotActive,
  },
  headerTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 2,
  },
  headerSubtitle: {
    color: NothingTheme.colors.accent,
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 2,
    marginTop: -2,
  },
  clearButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
    marginHorizontal: 24,
  },
  messagesContainer: {
    flex: 1,
  },
  messagesContent: {
    padding: 24,
    paddingBottom: 20,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 40,
  },
  emptyIconContainer: {
    width: 80,
    height: 80,
    borderRadius: 16,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
  },
  largeDotGrid: {
    width: 40,
    height: 40,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
  },
  largeDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: NothingTheme.colors.dotInactive,
  },
  largeDotActive: {
    backgroundColor: NothingTheme.colors.dotActive,
  },
  emptyTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 8,
  },
  emptySubtitle: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 13,
    marginBottom: 32,
  },
  suggestions: {
    width: '100%',
    gap: 8,
  },
  suggestionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  suggestionText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
  },
  messageBubble: {
    maxWidth: '85%',
    padding: 14,
    borderRadius: 8,
    marginBottom: 12,
  },
  userBubble: {
    backgroundColor: NothingTheme.colors.accent,
    alignSelf: 'flex-end',
  },
  assistantBubble: {
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  assistantDot: {
    width: 8,
    height: 8,
    marginTop: 6,
  },
  miniDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.dotInactive,
  },
  miniDotActive: {
    backgroundColor: NothingTheme.colors.dotActive,
  },
  messageText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    flex: 1,
  },
  userMessageText: {
    color: NothingTheme.colors.textPrimary,
  },
  loadingDots: {
    flexDirection: 'row',
    paddingVertical: 4,
  },
  loadingDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: NothingTheme.colors.textTertiary,
  },
  inputContainer: {
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: NothingTheme.colors.border,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    paddingLeft: 16,
    paddingRight: 6,
    paddingVertical: 6,
  },
  input: {
    flex: 1,
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    maxHeight: 100,
    paddingVertical: 8,
  },
  sendButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: NothingTheme.colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: {
    backgroundColor: NothingTheme.colors.surface,
  },
});
