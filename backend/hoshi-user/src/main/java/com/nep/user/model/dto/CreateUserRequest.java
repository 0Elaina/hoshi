package com.nep.user.model.dto;

import com.nep.user.util.UserValidationUtils;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record CreateUserRequest(
        @NotBlank(message = "用户名不能为空") @Pattern(regexp = UserValidationUtils.USERNAME_PATTERN, message = "用户名必须为3至32位英文字母、数字或下划线") String username,
        @NotBlank(message = "密码不能为空") @Pattern(regexp = UserValidationUtils.PASSWORD_PATTERN, message = "密码须为8至72位英文字母、数字或半角符号") String password,
        @Size(max = 32, message = "昵称长度不能超过32个字符") String nickname) {

    public CreateUserRequest {
        nickname = nickname == null ? null : nickname.strip();
    }
}
