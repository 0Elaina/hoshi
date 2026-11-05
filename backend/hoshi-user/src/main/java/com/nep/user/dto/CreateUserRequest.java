package com.nep.user.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record CreateUserRequest(
        @NotBlank(message = "用户名不能为空") @Pattern(regexp = USERNAME_PATTERN, message = "用户名必须为3至32位英文字母、数字或下划线") String username,
        @NotBlank(message = "密码不能为空") @Pattern(regexp = PASSWORD_PATTERN, message = "密码须为8至72位英文字母、数字或半角符号") String password,
        @Size(max = 32, message = "昵称长度不能超过32个字符") String nickname) {
    private static final String USERNAME_PATTERN = "[A-Za-z0-9_]{3,32}";

    private static final String PASSWORD_PATTERN = "[!-~]{8,72}";

    public CreateUserRequest {
        nickname = nickname == null ? null : nickname.strip();
    }
}
