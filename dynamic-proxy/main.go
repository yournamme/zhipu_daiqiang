package main

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/armon/go-socks5"
	"golang.org/x/net/proxy"
	"gopkg.in/yaml.v3"
)

// Config represents the application configuration
type Config struct {
	ProxyListURLs          []string `yaml:"proxy_list_urls"`
	SpecialProxyListUrls   []string `yaml:"special_proxy_list_urls"` // 支持复杂格式的代理URL列表
	HealthCheckConcurrency int      `yaml:"health_check_concurrency"`
	UpdateIntervalMinutes  int      `yaml:"update_interval_minutes"`
	HealthCheck            struct {
		TotalTimeoutSeconds          int    `yaml:"total_timeout_seconds"`
		TLSHandshakeThresholdSeconds int    `yaml:"tls_handshake_threshold_seconds"`
		Target                       string `yaml:"target"` // host:port to test through each proxy
	} `yaml:"health_check"`
	Ports struct {
		SOCKS5Strict  string `yaml:"socks5_strict"`
		SOCKS5Relaxed string `yaml:"socks5_relaxed"`
		HTTPStrict    string `yaml:"http_strict"`
		HTTPRelaxed   string `yaml:"http_relaxed"`
	} `yaml:"ports"`
}

// Global config variable
var config Config
var runtimeEnv envFileConfig

// Simple regex to extract ip:port from any format (used for special proxy lists)
// Matches: [IP]:[port] and ignores any protocol prefixes or extra text
var simpleProxyRegex = regexp.MustCompile(`([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}):([0-9]{1,5})`)

type proxyHealth struct {
	Addr    string
	Latency time.Duration
}

type envFileConfig struct {
	KDLWhiteIPEnabled               bool
	KDLSecretID                     string
	KDLSecretKey                    string
	KDLSecretTokenAPI               string
	KDLSignature                    string
	KDLWhiteIPAPI                   string
	KDLWhiteIPList                  string
	KDLWhiteIPWaitSeconds           int
	ProxyPoolMaxLatencyMS           int
	ProxyPoolFastWindow             int
	ProxyPoolFailureCooldownSeconds int
}

func loadDotEnvFile(path string) {
	file, err := os.Open(path)
	if err != nil {
		if !os.IsNotExist(err) {
			log.Printf("Warning: failed to open env file %s: %v", path, err)
		}
		return
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])
		value = strings.Trim(value, `"'`)
		if key == "" || os.Getenv(key) != "" {
			continue
		}
		if err := os.Setenv(key, value); err != nil {
			log.Printf("Warning: failed to set env %s from %s: %v", key, path, err)
		}
	}
	if err := scanner.Err(); err != nil {
		log.Printf("Warning: failed to read env file %s: %v", path, err)
	}
}

func loadDotEnvFiles() {
	loadDotEnvFile("../.env")
	loadDotEnvFile(".env")
}

func getenvDefault(key string, defaultValue string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return defaultValue
	}
	return value
}

func getenvBool(key string, defaultValue bool) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(key)))
	if value == "" {
		return defaultValue
	}
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

func getenvInt(key string, defaultValue int) int {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return defaultValue
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		log.Printf("Warning: invalid %s=%q, using default %d", key, value, defaultValue)
		return defaultValue
	}
	return parsed
}

func loadEnvConfig() envFileConfig {
	return envFileConfig{
		KDLWhiteIPEnabled:               getenvBool("KDL_WHITEIP_ENABLED", false),
		KDLSecretID:                     getenvDefault("KDL_SECRET_ID", ""),
		KDLSecretKey:                    getenvDefault("KDL_SECRET_KEY", ""),
		KDLSecretTokenAPI:               getenvDefault("KDL_SECRET_TOKEN_API", "https://auth.kdlapi.com/api/get_secret_token"),
		KDLSignature:                    getenvDefault("KDL_SIGNATURE", ""),
		KDLWhiteIPAPI:                   getenvDefault("KDL_WHITEIP_API", "https://dev.kdlapi.com/api/addwhiteip"),
		KDLWhiteIPList:                  getenvDefault("KDL_WHITEIP_LIST", ""),
		KDLWhiteIPWaitSeconds:           getenvInt("KDL_WHITEIP_WAIT_SECONDS", 65),
		ProxyPoolMaxLatencyMS:           getenvInt("PROXY_POOL_MAX_LATENCY_MS", 3000),
		ProxyPoolFastWindow:             getenvInt("PROXY_POOL_FAST_WINDOW", 32),
		ProxyPoolFailureCooldownSeconds: getenvInt("PROXY_POOL_FAILURE_COOLDOWN_SECONDS", 60),
	}
}

func getKDLSecretToken(client *http.Client, envCfg envFileConfig) (string, bool) {
	if envCfg.KDLSecretKey == "" {
		return envCfg.KDLSignature, envCfg.KDLSignature != ""
	}
	if envCfg.KDLSecretID == "" {
		log.Println("[KDL] KDL_SECRET_KEY is set but KDL_SECRET_ID is empty, cannot fetch secret token")
		return "", false
	}
	values := url.Values{}
	values.Set("secret_id", envCfg.KDLSecretID)
	values.Set("secret_key", envCfg.KDLSecretKey)

	log.Println("[KDL] Fetching KuaiDaili secret_token with SecretId/SecretKey...")
	resp, err := client.PostForm(envCfg.KDLSecretTokenAPI, values)
	if err != nil {
		log.Printf("[KDL] Failed to fetch secret_token: %v", err)
		return "", false
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if err != nil {
		log.Printf("[KDL] get_secret_token status=%d, failed to read response: %v", resp.StatusCode, err)
		return "", false
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		log.Printf("[KDL] get_secret_token returned status=%d, body=%s", resp.StatusCode, strings.TrimSpace(string(body)))
		return "", false
	}

	var apiResp struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
		Data struct {
			SecretToken string `json:"secret_token"`
			Expire      int    `json:"expire"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &apiResp); err != nil {
		log.Printf("[KDL] Failed to parse get_secret_token response: %v", err)
		return "", false
	}
	if apiResp.Code != 0 || apiResp.Data.SecretToken == "" {
		log.Printf("[KDL] get_secret_token failed with code=%d msg=%s", apiResp.Code, apiResp.Msg)
		return "", false
	}
	log.Printf("[KDL] secret_token fetched successfully, expire=%ds", apiResp.Data.Expire)
	return apiResp.Data.SecretToken, true
}

func addKDLWhiteIP(envCfg envFileConfig) {
	if !envCfg.KDLWhiteIPEnabled {
		return
	}
	if envCfg.KDLSecretID == "" {
		log.Println("[KDL] WhiteIP is enabled but KDL_SECRET_ID is empty, skipping")
		return
	}
	client := &http.Client{Timeout: 15 * time.Second}
	signature, ok := getKDLSecretToken(client, envCfg)
	if !ok {
		log.Println("[KDL] No usable secret_token/signature, skipping AddWhiteIP")
		return
	}

	endpoint, err := url.Parse(envCfg.KDLWhiteIPAPI)
	if err != nil {
		log.Printf("[KDL] Invalid KDL_WHITEIP_API %q: %v", envCfg.KDLWhiteIPAPI, err)
		return
	}
	query := endpoint.Query()
	query.Set("secret_id", envCfg.KDLSecretID)
	query.Set("signature", signature)
	query.Set("sign_type", "token")
	if envCfg.KDLWhiteIPList != "" {
		query.Set("iplist", envCfg.KDLWhiteIPList)
	}
	endpoint.RawQuery = query.Encode()

	log.Println("[KDL] Adding current server IP to KuaiDaili whitelist...")
	resp, err := client.Get(endpoint.String())
	if err != nil {
		log.Printf("[KDL] Failed to call AddWhiteIP API: %v", err)
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if err != nil {
		log.Printf("[KDL] AddWhiteIP status=%d, failed to read response: %v", resp.StatusCode, err)
		return
	}
	bodyText := strings.TrimSpace(string(body))
	log.Printf("[KDL] AddWhiteIP status=%d response=%s", resp.StatusCode, bodyText)

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		log.Println("[KDL] AddWhiteIP returned non-2xx status, proxy fetching will continue and may fail if whitelist is not ready")
		return
	}
	var apiResp struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
	}
	if err := json.Unmarshal(body, &apiResp); err == nil && apiResp.Code != 0 {
		log.Printf("[KDL] AddWhiteIP failed with code=%d msg=%s, proxy fetching will continue", apiResp.Code, apiResp.Msg)
		return
	}
	if envCfg.KDLWhiteIPWaitSeconds > 0 {
		log.Printf("[KDL] Waiting %d seconds for whitelist propagation...", envCfg.KDLWhiteIPWaitSeconds)
		time.Sleep(time.Duration(envCfg.KDLWhiteIPWaitSeconds) * time.Second)
	}
}

func sortProxyHealth(items []proxyHealth) {
	sort.Slice(items, func(i, j int) bool {
		if items[i].Latency == items[j].Latency {
			return items[i].Addr < items[j].Addr
		}
		return items[i].Latency < items[j].Latency
	})
}

func proxyAddrs(items []proxyHealth) []string {
	result := make([]string, len(items))
	for i, item := range items {
		result[i] = item.Addr
	}
	return result
}

func filterProxyHealthByLatency(items []proxyHealth, maxLatencyMS int) []proxyHealth {
	if maxLatencyMS <= 0 {
		return items
	}
	maxLatency := time.Duration(maxLatencyMS) * time.Millisecond
	filtered := items[:0]
	for _, item := range items {
		if item.Latency <= maxLatency {
			filtered = append(filtered, item)
		}
	}
	return filtered
}

func logProxyLatencySummary(mode string, items []proxyHealth) {
	if len(items) == 0 {
		return
	}
	var total time.Duration
	for _, item := range items {
		total += item.Latency
	}
	avg := total / time.Duration(len(items))
	fastest := items[0]
	slowest := items[len(items)-1]
	log.Printf("[%s] Latency sorted: count=%d fastest=%s/%dms slowest=%s/%dms avg=%dms",
		mode,
		len(items),
		fastest.Addr,
		fastest.Latency.Milliseconds(),
		slowest.Addr,
		slowest.Latency.Milliseconds(),
		avg.Milliseconds(),
	)
}

// loadConfig loads configuration from config.yaml
func loadConfig(filename string) (*Config, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse config file: %w", err)
	}

	// Validate config
	if len(cfg.ProxyListURLs) == 0 {
		return nil, fmt.Errorf("at least one proxy_list_url must be specified")
	}
	if cfg.HealthCheckConcurrency <= 0 {
		cfg.HealthCheckConcurrency = 200
	}
	if cfg.UpdateIntervalMinutes <= 0 {
		cfg.UpdateIntervalMinutes = 5
	}
	if cfg.HealthCheck.TotalTimeoutSeconds <= 0 {
		cfg.HealthCheck.TotalTimeoutSeconds = 8
	}
	if cfg.HealthCheck.TLSHandshakeThresholdSeconds <= 0 {
		cfg.HealthCheck.TLSHandshakeThresholdSeconds = 5
	}
	if cfg.Ports.SOCKS5Strict == "" {
		cfg.Ports.SOCKS5Strict = ":1080"
	}
	if cfg.Ports.SOCKS5Relaxed == "" {
		cfg.Ports.SOCKS5Relaxed = ":1082"
	}
	if cfg.Ports.HTTPStrict == "" {
		cfg.Ports.HTTPStrict = ":8080"
	}
	if cfg.Ports.HTTPRelaxed == "" {
		cfg.Ports.HTTPRelaxed = ":8082"
	}

	return &cfg, nil
}

type ProxyPool struct {
	proxies       []string
	mu            sync.RWMutex
	index         uint64
	window        int
	cooldownUntil map[string]time.Time
	updating      int32 // atomic flag to prevent concurrent updates
}

func NewProxyPool() *ProxyPool {
	return &ProxyPool{
		proxies:       make([]string, 0),
		cooldownUntil: make(map[string]time.Time),
	}
}

func (p *ProxyPool) Update(proxies []string, fastWindow int) {
	p.mu.Lock()
	defer p.mu.Unlock()

	oldCount := len(p.proxies)
	p.proxies = proxies
	p.window = fastWindow
	nextCooldown := make(map[string]time.Time)
	for _, proxyAddr := range proxies {
		if until, ok := p.cooldownUntil[proxyAddr]; ok && until.After(time.Now()) {
			nextCooldown[proxyAddr] = until
		}
	}
	p.cooldownUntil = nextCooldown
	// Reset index to 0 to avoid out-of-bounds issues
	atomic.StoreUint64(&p.index, 0)

	activeWindow := p.activeWindowLocked()
	log.Printf("Proxy pool updated: %d -> %d active proxies (fast_window=%d)", oldCount, len(proxies), activeWindow)
}

func (p *ProxyPool) activeWindowLocked() int {
	if len(p.proxies) == 0 {
		return 0
	}
	if p.window <= 0 || p.window > len(p.proxies) {
		return len(p.proxies)
	}
	return p.window
}

func (p *ProxyPool) MarkFailure(proxyAddr string) {
	cooldownSeconds := runtimeEnv.ProxyPoolFailureCooldownSeconds
	if cooldownSeconds <= 0 || proxyAddr == "" {
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cooldownUntil == nil {
		p.cooldownUntil = make(map[string]time.Time)
	}
	until := time.Now().Add(time.Duration(cooldownSeconds) * time.Second)
	p.cooldownUntil[proxyAddr] = until
	log.Printf("Proxy %s cooled down for %ds after failure", proxyAddr, cooldownSeconds)
}

func (p *ProxyPool) GetNext() (string, error) {
	p.mu.RLock()
	defer p.mu.RUnlock()

	if len(p.proxies) == 0 {
		return "", fmt.Errorf("no available proxies")
	}

	activeWindow := p.activeWindowLocked()
	now := time.Now()
	for attempts := 0; attempts < activeWindow; attempts++ {
		idx := (atomic.AddUint64(&p.index, 1) - 1) % uint64(activeWindow)
		proxyAddr := p.proxies[idx]
		until, cooling := p.cooldownUntil[proxyAddr]
		if !cooling || !until.After(now) {
			if cooling {
				delete(p.cooldownUntil, proxyAddr)
			}
			return proxyAddr, nil
		}
	}
	log.Println("All proxies in fast window are cooling down, falling back to the full pool")
	idx := (atomic.AddUint64(&p.index, 1) - 1) % uint64(len(p.proxies))
	return p.proxies[idx], nil
}

func (p *ProxyPool) GetAll() []string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	result := make([]string, len(p.proxies))
	copy(result, p.proxies)
	return result
}

// parseSpecialProxyURL 使用简单正则表达式从复杂格式中提取代理
// 支持格式：任何包含 ip:port 的行，自动忽略协议前缀和描述文本
// 例如：socks5://83.217.209.26:1 [[家宽] 英国] → 提取 83.217.209.26:1
func parseSpecialProxyURL(content string) ([]string, error) {
	var proxies []string
	proxySet := make(map[string]bool) // 用于去重

	lines := strings.Split(content, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// 使用简单正则直接提取 ip:port，忽略所有其他内容
		matches := simpleProxyRegex.FindStringSubmatch(line)
		if len(matches) >= 3 {
			ip := matches[1]
			port := matches[2]
			proxy := fmt.Sprintf("%s:%s", ip, port)

			// 去重
			if !proxySet[proxy] {
				proxySet[proxy] = true
				proxies = append(proxies, proxy)
			}
		}
	}

	return proxies, nil
}

func readProxySource(client *http.Client, source string) (string, error) {
	if strings.HasPrefix(source, "http://") || strings.HasPrefix(source, "https://") {
		resp, err := client.Get(source)
		if err != nil {
			return "", err
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return "", fmt.Errorf("unexpected status code %d", resp.StatusCode)
		}
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return "", err
		}
		return string(body), nil
	}

	data, err := os.ReadFile(source)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func fetchProxyList() ([]string, error) {
	client := &http.Client{
		Timeout: 30 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{
				InsecureSkipVerify: true, // Disable certificate verification
			},
		},
	}

	allProxies := make([]string, 0)
	proxySet := make(map[string]bool) // 用于去重

	// 处理普通代理源（简单格式，支持 HTTP(S) URL 或本地文件）
	for _, source := range config.ProxyListURLs {
		log.Printf("Fetching proxy list from regular source: %s", source)

		content, err := readProxySource(client, source)
		if err != nil {
			log.Printf("Warning: Failed to fetch from %s: %v", source, err)
			continue // 继续尝试其他源
		}

		count := 0
		scanner := bufio.NewScanner(strings.NewReader(content))
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			// Support formats: ip:port, http://ip:port, https://ip:port, socks5://ip:port, socks4://ip:port
			// Strip protocol prefixes using string operations (no regex for better performance)
			line = strings.TrimPrefix(line, "socks5://")
			line = strings.TrimPrefix(line, "socks4://")
			line = strings.TrimPrefix(line, "https://")
			line = strings.TrimPrefix(line, "http://")

			// 去重
			if !proxySet[line] {
				proxySet[line] = true
				allProxies = append(allProxies, line)
				count++
			}
		}

		log.Printf("Fetched %d proxies from regular source %s", count, source)
	}

	// 处理特殊代理URL（复杂格式）
	for _, url := range config.SpecialProxyListUrls {
		log.Printf("Fetching proxy list from special URL: %s", url)

		resp, err := client.Get(url)
		if err != nil {
			log.Printf("Warning: Failed to fetch from special URL %s: %v", url, err)
			continue
		}

		if resp.StatusCode != http.StatusOK {
			log.Printf("Warning: Unexpected status code %d from special URL %s", resp.StatusCode, url)
			resp.Body.Close()
			continue
		}

		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			log.Printf("Warning: Error reading body from special URL %s: %v", url, err)
			continue
		}

		content := string(body)
		// 使用特殊解析函数处理复杂格式
		specialProxies, err := parseSpecialProxyURL(content)
		if err != nil {
			log.Printf("Warning: Error parsing special proxies from %s: %v", url, err)
			continue
		}

		count := 0
		for _, proxy := range specialProxies {
			// All proxies are now in ip:port format for consistency
			if !proxySet[proxy] {
				proxySet[proxy] = true
				allProxies = append(allProxies, proxy)
				count++
			}
		}

		log.Printf("Fetched %d proxies from special URL %s", count, url)
	}

	if len(allProxies) == 0 {
		return nil, fmt.Errorf("no proxies fetched from any source")
	}

	log.Printf("Total unique proxies fetched: %d", len(allProxies))
	return allProxies, nil
}

func checkProxyHealth(proxyAddr string, strictMode bool) (time.Duration, bool) {
	// Create a context with timeout from config
	totalTimeout := time.Duration(config.HealthCheck.TotalTimeoutSeconds) * time.Second
	ctx, cancel := context.WithTimeout(context.Background(), totalTimeout)
	defer cancel()

	dialer, err := proxy.SOCKS5("tcp", proxyAddr, nil, proxy.Direct)
	if err != nil {
		return 0, false
	}

	// Use a channel to handle timeout
	type checkResult struct {
		latency time.Duration
		ok      bool
	}
	done := make(chan checkResult, 1)
	go func() {
		// Test HTTPS connection to verify TLS handshake works and is fast
		start := time.Now()

		target := config.HealthCheck.Target
		if target == "" {
			target = "www.google.com:443"
		}
		conn, err := dialer.Dial("tcp", target)
		if err != nil {
			done <- checkResult{ok: false}
			return
		}
		defer conn.Close()

		// Perform TLS handshake to test SSL performance
		serverName := target
		if idx := strings.LastIndex(target, ":"); idx != -1 {
			serverName = target[:idx]
		}
		tlsConn := tls.Client(conn, &tls.Config{
			ServerName:         serverName,
			InsecureSkipVerify: !strictMode,
		})

		err = tlsConn.Handshake()
		if err != nil {
			done <- checkResult{ok: false}
			return
		}
		tlsConn.Close()

		// Check if TLS handshake was fast enough (from config)
		elapsed := time.Since(start)
		threshold := time.Duration(config.HealthCheck.TLSHandshakeThresholdSeconds) * time.Second
		if elapsed > threshold {
			// Too slow, reject this proxy
			done <- checkResult{latency: elapsed, ok: false}
			return
		}

		done <- checkResult{latency: elapsed, ok: true}
	}()

	select {
	case result := <-done:
		return result.latency, result.ok
	case <-ctx.Done():
		return 0, false
	}
}

// HealthCheckResult holds the results of health check for both modes
type HealthCheckResult struct {
	Strict  []proxyHealth
	Relaxed []proxyHealth
}

func healthCheckProxies(proxies []string) HealthCheckResult {
	var wg sync.WaitGroup
	var mu sync.Mutex
	strictHealthy := make([]proxyHealth, 0)
	relaxedHealthy := make([]proxyHealth, 0)

	total := len(proxies)
	var checked int64
	var strictCount int64
	var relaxedCount int64

	// Use worker pool to limit concurrent checks (from config)
	semaphore := make(chan struct{}, config.HealthCheckConcurrency)

	// Progress reporter goroutine
	done := make(chan struct{})
	go func() {
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()

		lastChecked := int64(0)

		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				current := atomic.LoadInt64(&checked)
				strictCurrent := atomic.LoadInt64(&strictCount)
				relaxedCurrent := atomic.LoadInt64(&relaxedCount)

				// Only print if progress has changed
				if current != lastChecked {
					percentage := float64(current) / float64(total) * 100

					// Progress bar
					barWidth := 40
					filled := int(float64(barWidth) * float64(current) / float64(total))
					bar := strings.Repeat("█", filled) + strings.Repeat("░", barWidth-filled)

					log.Printf("[%s] %d/%d (%.1f%%) | Strict: %d | Relaxed: %d",
						bar, current, total, percentage, strictCurrent, relaxedCurrent)

					lastChecked = current
				}
			}
		}
	}()

	for _, proxyAddr := range proxies {
		wg.Add(1)
		go func(addr string) {
			defer wg.Done()
			semaphore <- struct{}{}
			defer func() { <-semaphore }()

			// Optimized: check strict mode first
			strictLatency, strictOK := checkProxyHealth(addr, true)

			if strictOK {
				// If strict mode passes, relaxed mode must pass too
				mu.Lock()
				strictHealthy = append(strictHealthy, proxyHealth{Addr: addr, Latency: strictLatency})
				relaxedHealthy = append(relaxedHealthy, proxyHealth{Addr: addr, Latency: strictLatency})
				mu.Unlock()
				atomic.AddInt64(&strictCount, 1)
				atomic.AddInt64(&relaxedCount, 1)
			} else {
				// Strict mode failed, try relaxed mode
				relaxedLatency, relaxedOK := checkProxyHealth(addr, false)
				if relaxedOK {
					mu.Lock()
					relaxedHealthy = append(relaxedHealthy, proxyHealth{Addr: addr, Latency: relaxedLatency})
					mu.Unlock()
					atomic.AddInt64(&relaxedCount, 1)
				}
			}
			atomic.AddInt64(&checked, 1)
		}(proxyAddr)
	}

	wg.Wait()
	close(done)

	// Final progress update
	log.Printf("[%s] %d/%d (100.0%%) | Strict: %d | Relaxed: %d",
		strings.Repeat("█", 40), total, total, len(strictHealthy), len(relaxedHealthy))

	sortProxyHealth(strictHealthy)
	sortProxyHealth(relaxedHealthy)
	logProxyLatencySummary("STRICT", strictHealthy)
	logProxyLatencySummary("RELAXED", relaxedHealthy)
	strictBeforeFilter := len(strictHealthy)
	relaxedBeforeFilter := len(relaxedHealthy)
	strictHealthy = filterProxyHealthByLatency(strictHealthy, runtimeEnv.ProxyPoolMaxLatencyMS)
	relaxedHealthy = filterProxyHealthByLatency(relaxedHealthy, runtimeEnv.ProxyPoolMaxLatencyMS)
	if runtimeEnv.ProxyPoolMaxLatencyMS > 0 {
		log.Printf("Proxy latency cutoff applied: max=%dms | Strict: %d -> %d | Relaxed: %d -> %d",
			runtimeEnv.ProxyPoolMaxLatencyMS,
			strictBeforeFilter,
			len(strictHealthy),
			relaxedBeforeFilter,
			len(relaxedHealthy),
		)
	}

	return HealthCheckResult{
		Strict:  strictHealthy,
		Relaxed: relaxedHealthy,
	}
}

func updateProxyPool(strictPool *ProxyPool, relaxedPool *ProxyPool) {
	// Check if an update is already in progress
	if !atomic.CompareAndSwapInt32(&strictPool.updating, 0, 1) {
		log.Println("Proxy update already in progress, skipping...")
		return
	}
	defer atomic.StoreInt32(&strictPool.updating, 0)

	log.Println("Fetching proxy list...")
	proxies, err := fetchProxyList()
	if err != nil {
		log.Printf("Error fetching proxy list: %v", err)
		return
	}

	log.Printf("Fetched %d proxies, starting health check...", len(proxies))
	result := healthCheckProxies(proxies)

	// Update strict pool
	if len(result.Strict) > 0 {
		strictPool.Update(proxyAddrs(result.Strict), runtimeEnv.ProxyPoolFastWindow)
		log.Printf("[STRICT] Pool updated with %d healthy proxies", len(result.Strict))
	} else {
		log.Println("[STRICT] Warning: No healthy proxies found, keeping existing pool")
	}

	// Update relaxed pool
	if len(result.Relaxed) > 0 {
		relaxedPool.Update(proxyAddrs(result.Relaxed), runtimeEnv.ProxyPoolFastWindow)
		log.Printf("[RELAXED] Pool updated with %d healthy proxies", len(result.Relaxed))
	} else {
		log.Println("[RELAXED] Warning: No healthy proxies found, keeping existing pool")
	}
}

func startProxyUpdater(strictPool *ProxyPool, relaxedPool *ProxyPool, initialSync bool) {
	if initialSync {
		// Initial update synchronously to ensure we have proxies before starting servers
		log.Println("Performing initial proxy update...")
		updateProxyPool(strictPool, relaxedPool)
	}

	// Periodic updates - each update runs in its own goroutine to avoid blocking
	updateInterval := time.Duration(config.UpdateIntervalMinutes) * time.Minute
	ticker := time.NewTicker(updateInterval)
	go func() {
		for range ticker.C {
			go updateProxyPool(strictPool, relaxedPool)
		}
	}()
}

// SOCKS5 Proxy Server
type CustomDialer struct {
	pool *ProxyPool
	mode string // "STRICT" or "RELAXED"
}

// LoggedConn wraps a net.Conn to log when it's closed
type LoggedConn struct {
	net.Conn
	addr       string
	proxyAddr  string
	closed     bool
	bytesRead  int64
	bytesWrite int64
}

func (c *LoggedConn) Close() error {
	if !c.closed {
		c.closed = true
		log.Printf("[SOCKS5] Connection closed: %s via proxy %s (read: %d bytes, wrote: %d bytes)",
			c.addr, c.proxyAddr, c.bytesRead, c.bytesWrite)
	}
	return c.Conn.Close()
}

func (c *LoggedConn) Read(b []byte) (n int, err error) {
	n, err = c.Conn.Read(b)
	if n > 0 {
		atomic.AddInt64(&c.bytesRead, int64(n))
	}
	if err != nil && err != io.EOF {
		log.Printf("[SOCKS5] Read error for %s via proxy %s after %d bytes: %v",
			c.addr, c.proxyAddr, c.bytesRead, err)
	}
	return n, err
}

func (c *LoggedConn) Write(b []byte) (n int, err error) {
	n, err = c.Conn.Write(b)
	if n > 0 {
		atomic.AddInt64(&c.bytesWrite, int64(n))
	}
	if err != nil {
		log.Printf("[SOCKS5] Write error for %s via proxy %s after %d bytes: %v",
			c.addr, c.proxyAddr, c.bytesWrite, err)
	}
	return n, err
}

func (d *CustomDialer) Dial(ctx context.Context, network, addr string) (net.Conn, error) {
	log.Printf("[SOCKS5-%s] Incoming request: %s -> %s", d.mode, network, addr)

	proxyAddr, err := d.pool.GetNext()
	if err != nil {
		log.Printf("[SOCKS5-%s] ERROR: No proxy available for %s: %v", d.mode, addr, err)
		return nil, err
	}

	log.Printf("[SOCKS5-%s] Using proxy %s for %s", d.mode, proxyAddr, addr)

	dialer, err := proxy.SOCKS5("tcp", proxyAddr, nil, proxy.Direct)
	if err != nil {
		log.Printf("[SOCKS5-%s] ERROR: Failed to create dialer for proxy %s: %v", d.mode, proxyAddr, err)
		return nil, fmt.Errorf("failed to create SOCKS5 dialer: %w", err)
	}

	conn, err := dialer.Dial(network, addr)
	if err != nil {
		log.Printf("[SOCKS5-%s] ERROR: Failed to connect to %s via proxy %s: %v", d.mode, addr, proxyAddr, err)
		d.pool.MarkFailure(proxyAddr)
		return nil, fmt.Errorf("failed to dial through proxy %s: %w", proxyAddr, err)
	}

	log.Printf("[SOCKS5-%s] SUCCESS: Connected to %s via proxy %s", d.mode, addr, proxyAddr)

	// Wrap the connection to log read/write errors and close events
	loggedConn := &LoggedConn{
		Conn:      conn,
		addr:      addr,
		proxyAddr: proxyAddr,
		closed:    false,
	}

	return loggedConn, nil
}

func startSOCKS5Server(pool *ProxyPool, port string, mode string) error {
	// Create a custom logger with mode-specific prefix
	socks5Logger := log.New(log.Writer(), fmt.Sprintf("[SOCKS5-%s-LIB] ", mode), log.LstdFlags)

	conf := &socks5.Config{
		Dial: func(ctx context.Context, network, addr string) (net.Conn, error) {
			dialer := &CustomDialer{pool: pool, mode: mode}
			return dialer.Dial(ctx, network, addr)
		},
		Logger: socks5Logger,
	}

	server, err := socks5.New(conf)
	if err != nil {
		return fmt.Errorf("failed to create SOCKS5 server: %w", err)
	}

	log.Printf("[%s] SOCKS5 proxy server listening on %s", mode, port)
	return server.ListenAndServe("tcp", port)
}

// HTTP Proxy Server
func handleHTTPProxy(w http.ResponseWriter, r *http.Request, pool *ProxyPool, mode string) {
	log.Printf("[HTTP-%s] Incoming request: %s %s from %s", mode, r.Method, r.URL.String(), r.RemoteAddr)

	proxyAddr, err := pool.GetNext()
	if err != nil {
		log.Printf("[HTTP-%s] ERROR: No proxy available for %s %s: %v", mode, r.Method, r.URL.String(), err)
		http.Error(w, "No available proxies", http.StatusServiceUnavailable)
		return
	}

	log.Printf("[HTTP-%s] Using proxy %s for %s %s", mode, proxyAddr, r.Method, r.URL.String())

	// Create SOCKS5 dialer
	dialer, err := proxy.SOCKS5("tcp", proxyAddr, nil, proxy.Direct)
	if err != nil {
		log.Printf("[HTTP-%s] ERROR: Failed to create dialer for proxy %s: %v", mode, proxyAddr, err)
		http.Error(w, "Failed to create proxy dialer", http.StatusInternalServerError)
		return
	}

	// Handle CONNECT method for HTTPS
	if r.Method == http.MethodConnect {
		handleHTTPSProxy(w, r, pool, dialer, proxyAddr, mode)
		return
	}

	// Handle regular HTTP requests
	transport := &http.Transport{
		Dial: dialer.Dial,
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, // Disable certificate verification
		},
	}

	client := &http.Client{
		Transport: transport,
		Timeout:   30 * time.Second,
	}

	// Create new request
	proxyReq, err := http.NewRequest(r.Method, r.URL.String(), r.Body)
	if err != nil {
		http.Error(w, "Failed to create proxy request", http.StatusInternalServerError)
		return
	}

	// Copy headers
	for key, values := range r.Header {
		for _, value := range values {
			proxyReq.Header.Add(key, value)
		}
	}

	// Send request
	resp, err := client.Do(proxyReq)
	if err != nil {
		log.Printf("[HTTP-%s] ERROR: Request failed for %s: %v", mode, r.URL.String(), err)
		pool.MarkFailure(proxyAddr)
		http.Error(w, fmt.Sprintf("Proxy request failed: %v", err), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	log.Printf("[HTTP-%s] SUCCESS: Got response %d for %s", mode, resp.StatusCode, r.URL.String())

	// Copy response headers
	for key, values := range resp.Header {
		for _, value := range values {
			w.Header().Add(key, value)
		}
	}

	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}

func handleHTTPSProxy(w http.ResponseWriter, r *http.Request, pool *ProxyPool, dialer proxy.Dialer, proxyAddr string, mode string) {
	log.Printf("[HTTPS-%s] Connecting to %s via proxy %s", mode, r.Host, proxyAddr)

	// Connect to target through SOCKS5 proxy with a hard timeout so a hanging
	// upstream proxy fails fast instead of blocking for 15-20 s.
	upstreamTimeout := time.Duration(config.HealthCheck.TotalTimeoutSeconds+2) * time.Second
	type dialResult struct {
		conn net.Conn
		err  error
	}
	ch := make(chan dialResult, 1)
	go func() {
		conn, err := dialer.Dial("tcp", r.Host)
		ch <- dialResult{conn, err}
	}()

	var targetConn net.Conn
	select {
	case res := <-ch:
		if res.err != nil {
			log.Printf("[HTTPS-%s] ERROR: Failed to connect to %s via proxy %s: %v", mode, r.Host, proxyAddr, res.err)
			pool.MarkFailure(proxyAddr)
			http.Error(w, "Failed to connect to target", http.StatusBadGateway)
			return
		}
		targetConn = res.conn
	case <-time.After(upstreamTimeout):
		log.Printf("[HTTPS-%s] TIMEOUT: upstream proxy %s took >%s for %s", mode, proxyAddr, upstreamTimeout, r.Host)
		pool.MarkFailure(proxyAddr)
		http.Error(w, "Upstream proxy timeout", http.StatusGatewayTimeout)
		return
	}
	defer targetConn.Close()

	// Hijack the connection
	hijacker, ok := w.(http.Hijacker)
	if !ok {
		log.Printf("[HTTPS-%s] ERROR: Hijacking not supported for %s", mode, r.Host)
		http.Error(w, "Hijacking not supported", http.StatusInternalServerError)
		return
	}

	clientConn, _, err := hijacker.Hijack()
	if err != nil {
		log.Printf("[HTTPS-%s] ERROR: Failed to hijack connection for %s: %v", mode, r.Host, err)
		http.Error(w, "Failed to hijack connection", http.StatusInternalServerError)
		return
	}
	defer clientConn.Close()

	// Send 200 Connection Established
	clientConn.Write([]byte("HTTP/1.1 200 Connection Established\r\n\r\n"))
	log.Printf("[HTTPS-%s] SUCCESS: Tunnel established to %s via proxy %s", mode, r.Host, proxyAddr)

	// Bidirectional copy
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		io.Copy(targetConn, clientConn)
	}()

	go func() {
		defer wg.Done()
		io.Copy(clientConn, targetConn)
	}()

	wg.Wait()
}

func startHTTPServer(pool *ProxyPool, port string, mode string) error {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handleHTTPProxy(w, r, pool, mode)
	})

	server := &http.Server{
		Addr:    port,
		Handler: handler,
	}

	log.Printf("[%s] HTTP proxy server listening on %s", mode, port)
	return server.ListenAndServe()
}

func main() {
	log.Println("Starting Dynamic Proxy Server...")
	loadDotEnvFiles()
	envCfg := loadEnvConfig()
	runtimeEnv = envCfg
	addKDLWhiteIP(envCfg)

	// Load configuration
	cfg, err := loadConfig("config.yaml")
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}
	config = *cfg

	// Log configuration
	log.Printf("Configuration loaded:")
	log.Printf("  - Proxy sources: %d", len(config.ProxyListURLs))
	for i, url := range config.ProxyListURLs {
		log.Printf("    [%d] %s", i+1, url)
	}
	log.Printf("  - Health check concurrency: %d", config.HealthCheckConcurrency)
	log.Printf("  - Update interval: %d minutes", config.UpdateIntervalMinutes)
	log.Printf("  - Health check timeout: %ds (TLS threshold: %ds)",
		config.HealthCheck.TotalTimeoutSeconds,
		config.HealthCheck.TLSHandshakeThresholdSeconds)
	log.Printf("  - SOCKS5 Strict port: %s", config.Ports.SOCKS5Strict)
	log.Printf("  - SOCKS5 Relaxed port: %s", config.Ports.SOCKS5Relaxed)
	log.Printf("  - HTTP Strict port: %s", config.Ports.HTTPStrict)
	log.Printf("  - HTTP Relaxed port: %s", config.Ports.HTTPRelaxed)
	log.Printf("  - Proxy pool max latency: %dms", runtimeEnv.ProxyPoolMaxLatencyMS)
	log.Printf("  - Proxy pool fast window: %d", runtimeEnv.ProxyPoolFastWindow)
	log.Printf("  - Proxy pool failure cooldown: %ds", runtimeEnv.ProxyPoolFailureCooldownSeconds)

	// Create two proxy pools
	strictPool := NewProxyPool()
	relaxedPool := NewProxyPool()

	// Start proxy updater with initial synchronous update
	startProxyUpdater(strictPool, relaxedPool, true)

	// Check proxy pool status
	strictCount := len(strictPool.GetAll())
	relaxedCount := len(relaxedPool.GetAll())

	if strictCount == 0 {
		log.Println("[STRICT] Warning: No healthy proxies available")
		log.Println("[STRICT] Strict mode servers will return errors until proxies become available")
	} else {
		log.Printf("[STRICT] Successfully loaded %d healthy proxies", strictCount)
	}

	if relaxedCount == 0 {
		log.Println("[RELAXED] Warning: No healthy proxies available")
		log.Println("[RELAXED] Relaxed mode servers will return errors until proxies become available")
	} else {
		log.Printf("[RELAXED] Successfully loaded %d healthy proxies", relaxedCount)
	}

	// Start servers (4 servers total)
	var wg sync.WaitGroup
	wg.Add(4)

	// SOCKS5 Strict
	go func() {
		defer wg.Done()
		if err := startSOCKS5Server(strictPool, config.Ports.SOCKS5Strict, "STRICT"); err != nil {
			log.Fatalf("[STRICT] SOCKS5 server error: %v", err)
		}
	}()

	// SOCKS5 Relaxed
	go func() {
		defer wg.Done()
		if err := startSOCKS5Server(relaxedPool, config.Ports.SOCKS5Relaxed, "RELAXED"); err != nil {
			log.Fatalf("[RELAXED] SOCKS5 server error: %v", err)
		}
	}()

	// HTTP Strict
	go func() {
		defer wg.Done()
		if err := startHTTPServer(strictPool, config.Ports.HTTPStrict, "STRICT"); err != nil {
			log.Fatalf("[STRICT] HTTP server error: %v", err)
		}
	}()

	// HTTP Relaxed
	go func() {
		defer wg.Done()
		if err := startHTTPServer(relaxedPool, config.Ports.HTTPRelaxed, "RELAXED"); err != nil {
			log.Fatalf("[RELAXED] HTTP server error: %v", err)
		}
	}()

	log.Println("All servers started successfully")
	log.Println("  [STRICT] SOCKS5: " + config.Ports.SOCKS5Strict + " | HTTP: " + config.Ports.HTTPStrict)
	log.Println("  [RELAXED] SOCKS5: " + config.Ports.SOCKS5Relaxed + " | HTTP: " + config.Ports.HTTPRelaxed)
	log.Printf("Proxy pools will update every %d minutes in background...", config.UpdateIntervalMinutes)
	wg.Wait()
}
