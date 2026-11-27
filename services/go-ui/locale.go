package main

import "net/http"

const languageCookie = "upspotify-language"

type dashboardLanguage struct {
	Lang     string
	Messages map[string]string
	Text     func(string) string
}

func dashboardLocale(w http.ResponseWriter, r *http.Request) dashboardLanguage {
	lang := r.URL.Query().Get("lang")
	if lang == "en" || lang == "es" {
		http.SetCookie(w, &http.Cookie{
			Name: languageCookie, Value: lang, Path: "/", MaxAge: 31536000,
			SameSite: http.SameSiteLaxMode,
		})
	} else {
		lang = "es"
		if cookie, err := r.Cookie(languageCookie); err == nil && cookie.Value == "en" {
			lang = "en"
		}
	}
	messages := map[string]string{}
	if lang == "es" {
		messages = indexerSpanish
	}
	return dashboardLanguage{Lang: lang, Messages: messages, Text: func(message string) string {
		if translation, ok := messages[message]; ok {
			return translation
		}
		return message
	}}
}
