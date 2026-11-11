package apperr

import "hoshi/backend/internal/apicode"

type Error struct {
	code          apicode.Code
	publicMessage string
}

func New(code apicode.Code) *Error {
	return &Error{code: code}
}

func NewWithMessage(code apicode.Code, publicMessage string) *Error {
	return &Error{code: code, publicMessage: publicMessage}
}

func (e *Error) APICode() apicode.Code {
	return e.code
}

func (e *Error) PublicMessage() string {
	return e.publicMessage
}

func (e *Error) Error() string {
	message := e.publicMessage
	if message == "" {
		message = e.code.Message()
	}
	return e.code.Value() + ": " + message
}
