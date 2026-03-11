package db

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
)

// Client is a minimal Supabase PostgREST HTTP client
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

// DB is the global Supabase client instance
var DB *Client

// Init creates the global DB client from environment variables
func Init() {
	url := os.Getenv("SUPABASE_URL")
	key := os.Getenv("SUPABASE_SERVICE_ROLE_KEY")
	if url == "" || key == "" {
		panic("missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
	}
	DB = &Client{
		baseURL:    url,
		apiKey:     key,
		httpClient: &http.Client{},
	}
}

// pgError is the error shape returned by PostgREST
type pgError struct {
	Message string `json:"message"`
	Code    string `json:"code"`
}

func (c *Client) request(method, table string, query string, body interface{}, prefer string, result interface{}) error {
	var bodyReader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		bodyReader = bytes.NewReader(b)
	}

	url := c.baseURL + "/rest/v1/" + table
	if query != "" {
		url += "?" + query
	}

	req, err := http.NewRequest(method, url, bodyReader)
	if err != nil {
		return err
	}

	req.Header.Set("apikey", c.apiKey)
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")
	if prefer != "" {
		req.Header.Set("Prefer", prefer)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	if resp.StatusCode >= 400 {
		var pge pgError
		json.Unmarshal(respBody, &pge) //nolint:errcheck
		return fmt.Errorf("supabase %d: %s", resp.StatusCode, pge.Message)
	}

	if result != nil && len(respBody) > 0 && string(respBody) != "null" {
		return json.Unmarshal(respBody, result)
	}
	return nil
}

// Select executes a GET query and decodes the array response into result
func (c *Client) Select(table, query string, result interface{}) error {
	return c.request("GET", table, query, nil, "", result)
}

// Insert inserts rows and decodes the returned array into result.
// Pass nil for result if no return value is needed.
func (c *Client) Insert(table string, body interface{}, result interface{}) error {
	prefer := "return=representation"
	return c.request("POST", table, "", body, prefer, result)
}

// Update executes a PATCH and discards the response body
func (c *Client) Update(table, query string, body interface{}) error {
	return c.request("PATCH", table, query, body, "", nil)
}

// VerifyToken calls Supabase Auth to validate a JWT and returns the user's ID
func (c *Client) VerifyToken(token string) (string, error) {
	req, err := http.NewRequest("GET", c.baseURL+"/auth/v1/user", nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("apikey", c.apiKey)
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("invalid or expired token")
	}

	var user struct {
		ID string `json:"id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&user); err != nil {
		return "", err
	}
	if user.ID == "" {
		return "", fmt.Errorf("invalid token: no user id")
	}
	return user.ID, nil
}
