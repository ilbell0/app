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
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
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
  const { t, language } = useLanguage();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollViewRef = useRef<ScrollView>(null);

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
          ? 'Mi dispiace, si è verificato un errore. Riprova più tardi.'
          : 'Sorry, an error occurred. Please try again later.',
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
      setTimeout(() => {
        scrollViewRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  };

  const clearHistory = () => {
    setMessages([]);
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { paddingTop: insets.top }]}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={0}
    >
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <View style={styles.aiIcon}>
            <Ionicons name="sparkles" size={24} color="#10b981" />
          </View>
          <Text style={styles.headerTitle}>
            {language === 'it' ? 'AI Tattico' : 'Tactical AI'}
          </Text>
        </View>
        {messages.length > 0 && (
          <TouchableOpacity onPress={clearHistory}>
            <Ionicons name="trash-outline" size={24} color="rgba(255,255,255,0.5)" />
          </TouchableOpacity>
        )}
      </View>

      {/* Messages */}
      <ScrollView
        ref={scrollViewRef}
        style={styles.messagesContainer}
        contentContainerStyle={styles.messagesContent}
        onContentSizeChange={() => scrollViewRef.current?.scrollToEnd({ animated: true })}
      >
        {messages.length === 0 ? (
          <View style={styles.emptyState}>
            <View style={styles.emptyIcon}>
              <Ionicons name="chatbubbles-outline" size={48} color="rgba(255,255,255,0.2)" />
            </View>
            <Text style={styles.emptyTitle}>
              {language === 'it' ? 'Ciao! Come posso aiutarti?' : 'Hi! How can I help you?'}
            </Text>
            <Text style={styles.emptySubtitle}>
              {language === 'it'
                ? 'Chiedimi di formazioni, tattiche, giocatori...'
                : 'Ask me about formations, tactics, players...'}
            </Text>
            
            {/* Quick suggestions */}
            <View style={styles.suggestions}>
              <TouchableOpacity 
                style={styles.suggestionChip}
                onPress={() => setInput(language === 'it' ? 'Come contrastare il 4-3-3?' : 'How to counter 4-3-3?')}
              >
                <Text style={styles.suggestionText}>
                  {language === 'it' ? 'Come contrastare il 4-3-3?' : 'How to counter 4-3-3?'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={styles.suggestionChip}
                onPress={() => setInput(language === 'it' ? 'Miglior formazione META 2026' : 'Best META formation 2026')}
              >
                <Text style={styles.suggestionText}>
                  {language === 'it' ? 'Miglior formazione META 2026' : 'Best META formation 2026'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={styles.suggestionChip}
                onPress={() => setInput(language === 'it' ? 'Tattica per avversario più forte' : 'Tactics for stronger opponent')}
              >
                <Text style={styles.suggestionText}>
                  {language === 'it' ? 'Tattica per avversario più forte' : 'Tactics for stronger opponent'}
                </Text>
              </TouchableOpacity>
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
                <View style={styles.assistantIcon}>
                  <Ionicons name="sparkles" size={16} color="#10b981" />
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
            <View style={styles.assistantIcon}>
              <Ionicons name="sparkles" size={16} color="#10b981" />
            </View>
            <ActivityIndicator size="small" color="#10b981" />
          </View>
        )}
      </ScrollView>

      {/* Input */}
      <View style={[styles.inputContainer, { paddingBottom: insets.bottom + 10 }]}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder={language === 'it' ? 'Scrivi un messaggio...' : 'Type a message...'}
          placeholderTextColor="rgba(255,255,255,0.4)"
          multiline
          maxLength={500}
          onSubmitEditing={sendMessage}
        />
        <TouchableOpacity
          style={[styles.sendButton, (!input.trim() || loading) && styles.sendButtonDisabled]}
          onPress={sendMessage}
          disabled={!input.trim() || loading}
        >
          <Ionicons name="send" size={20} color="#fff" />
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
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
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  aiIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(16,185,129,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  messagesContainer: {
    flex: 1,
  },
  messagesContent: {
    padding: 20,
    paddingBottom: 20,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 40,
  },
  emptyIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  emptyTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 8,
    textAlign: 'center',
  },
  emptySubtitle: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 14,
    textAlign: 'center',
    marginBottom: 24,
  },
  suggestions: {
    width: '100%',
    gap: 10,
  },
  suggestionChip: {
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.2)',
  },
  suggestionText: {
    color: '#10b981',
    fontSize: 14,
    textAlign: 'center',
  },
  messageBubble: {
    maxWidth: '85%',
    padding: 14,
    borderRadius: 16,
    marginBottom: 12,
  },
  userBubble: {
    backgroundColor: '#10b981',
    alignSelf: 'flex-end',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: 'rgba(255,255,255,0.08)',
    alignSelf: 'flex-start',
    borderBottomLeftRadius: 4,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  assistantIcon: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: 'rgba(16,185,129,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  messageText: {
    color: 'rgba(255,255,255,0.9)',
    fontSize: 15,
    lineHeight: 22,
    flex: 1,
  },
  userMessageText: {
    color: '#fff',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: 16,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.1)',
    gap: 12,
  },
  input: {
    flex: 1,
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 20,
    paddingHorizontal: 18,
    paddingVertical: 12,
    color: '#fff',
    fontSize: 15,
    maxHeight: 100,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  sendButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#10b981',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: {
    backgroundColor: 'rgba(16,185,129,0.3)',
  },
});
