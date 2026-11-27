package main

import (
	"html/template"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestIndexerLanguages(t *testing.T) {
	page, err := template.ParseFiles("templates/index.html")
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		request string
		lang    string
		heading string
	}{
		{"/", "es", "Agrega música a UPSpotify"},
		{"/?lang=en", "en", "Add music to UPSpotify"},
	} {
		t.Run(tc.lang, func(t *testing.T) {
			request := httptest.NewRequest("GET", tc.request, nil)
			recorder := httptest.NewRecorder()
			locale := dashboardLocale(recorder, request)
			if err := page.ExecuteTemplate(recorder, "index.html", locale); err != nil {
				t.Fatal(err)
			}
			body := recorder.Body.String()
			if !strings.Contains(body, `<html lang="`+tc.lang+`">`) || !strings.Contains(body, tc.heading) {
				t.Fatal("rendered language or heading is missing")
			}
			if strings.Contains(body, `id="wsChip"`) || strings.Contains(body, `id="apiChip"`) {
				t.Fatal("connection badge is visible in the rendered template")
			}
			if tc.lang == "en" {
				cookies := recorder.Result().Cookies()
				if len(cookies) != 1 {
					t.Fatal("language preference cookie is missing")
				}
				next := httptest.NewRequest("GET", "/", nil)
				next.AddCookie(cookies[0])
				if dashboardLocale(httptest.NewRecorder(), next).Lang != "en" {
					t.Fatal("preferred language was not restored")
				}
			}
		})
	}
}
