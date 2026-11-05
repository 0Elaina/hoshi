package com.nep.user.dto;

import com.nep.user.util.UserValidationUtils;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

public record ResetUserPasswordRequest(
        @NotBlank(message = "新密码不能为空") @Pattern(regexp = UserValidationUtils.PASSWORD_PATTERN, message = "密码须为8至72位英文字母、数字或半角符号") String newPassword) {

}
