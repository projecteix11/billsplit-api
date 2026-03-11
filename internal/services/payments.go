package services

import (
	"crypto/cipher"
	"crypto/des"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"time"

	"billsplit/api/internal/db"
	"billsplit/api/internal/types"
)

func redsysSecret() string {
	if v := os.Getenv("REDSYS_SECRET"); v != "" {
		return v
	}
	return "sq7HjrUOBfKmC576ILgskD900SqIlHkI8awNPoDg"
}

func redsysMerchantCode() string {
	if v := os.Getenv("REDSYS_MERCHANT_CODE"); v != "" {
		return v
	}
	return "999008881"
}

func redsysTerminal() string {
	if v := os.Getenv("REDSYS_TERMINAL"); v != "" {
		return v
	}
	return "001"
}

const redsysURL = "https://sis-t.redsys.es:25443/sis/realizarPago"

// deriveKey replicates the 3DES-CBC key derivation used by Redsys
func deriveKey(secret, orderNumber string) ([]byte, error) {
	keyBytes, err := base64.StdEncoding.DecodeString(secret)
	if err != nil {
		return nil, fmt.Errorf("decode redsys secret: %w", err)
	}
	// 3DES requires exactly 24 bytes
	if len(keyBytes) < 24 {
		padded := make([]byte, 24)
		copy(padded, keyBytes)
		keyBytes = padded
	} else {
		keyBytes = keyBytes[:24]
	}

	// Pad orderNumber to nearest multiple of 8 with null bytes
	l := ((len(orderNumber) + 7) / 8) * 8
	padded := make([]byte, l)
	copy(padded, []byte(orderNumber))

	block, err := des.NewTripleDESCipher(keyBytes)
	if err != nil {
		return nil, fmt.Errorf("create 3des cipher: %w", err)
	}

	iv := make([]byte, des.BlockSize) // zero IV
	mode := cipher.NewCBCEncrypter(block, iv)
	dst := make([]byte, l)
	mode.CryptBlocks(dst, padded)

	return dst, nil
}

// RedsysSignResult holds the signed parameters for a Redsys payment request
type RedsysSignResult struct {
	DsMerchantParameters string `json:"Ds_MerchantParameters"`
	DsSignature          string `json:"Ds_Signature"`
	DsSignatureVersion   string `json:"Ds_SignatureVersion"`
	RedsysURL            string `json:"redsysUrl"`
	OrderNumber          string `json:"orderNumber"`
}

// SignRedsys builds and signs a Redsys payment request
func SignRedsys(amount float64, urlOk, urlKo string) (*RedsysSignResult, error) {
	orderNumber := strconv.FormatInt(time.Now().UnixMilli(), 10)
	if len(orderNumber) > 12 {
		orderNumber = orderNumber[len(orderNumber)-12:]
	}
	amountCents := strconv.Itoa(int(amount * 100))

	params := map[string]string{
		"DS_MERCHANT_AMOUNT":          amountCents,
		"DS_MERCHANT_ORDER":           orderNumber,
		"DS_MERCHANT_MERCHANTCODE":    redsysMerchantCode(),
		"DS_MERCHANT_TERMINAL":        redsysTerminal(),
		"DS_MERCHANT_TRANSACTIONTYPE": "0",
		"DS_MERCHANT_CURRENCY":        "978",
		"DS_MERCHANT_URLOK":           urlOk,
		"DS_MERCHANT_URLKO":           urlKo,
	}

	paramsJSON, err := json.Marshal(params)
	if err != nil {
		return nil, err
	}
	merchantParams := base64.StdEncoding.EncodeToString(paramsJSON)

	derivedKey, err := deriveKey(redsysSecret(), orderNumber)
	if err != nil {
		return nil, err
	}

	mac := hmac.New(sha256.New, derivedKey)
	mac.Write([]byte(merchantParams))
	signature := base64.StdEncoding.EncodeToString(mac.Sum(nil))

	return &RedsysSignResult{
		DsMerchantParameters: merchantParams,
		DsSignature:          signature,
		DsSignatureVersion:   "HMAC_SHA256_V1",
		RedsysURL:            redsysURL,
		OrderNumber:          orderNumber,
	}, nil
}

// CreatePayment inserts a payment record and returns it
func CreatePayment(orderID string, amount float64, method string) (*types.Payment, error) {
	row := map[string]interface{}{
		"order_id":       orderID,
		"amount":         amount,
		"tip_amount":     0,
		"total_charged":  amount,
		"payment_method": method,
		"status":         "confirmed",
	}

	var inserted []types.Payment
	if err := db.DB.Insert("payments", row, &inserted); err != nil {
		return nil, err
	}
	if len(inserted) == 0 {
		return nil, fmt.Errorf("failed to create payment")
	}
	return &inserted[0], nil
}
