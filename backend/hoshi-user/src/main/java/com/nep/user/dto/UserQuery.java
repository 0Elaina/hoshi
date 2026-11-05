package com.nep.user.dto;

import org.springframework.util.StringUtils;

import com.nep.common.page.PageQuery;
import com.nep.user.enums.UserStatus;

import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class UserQuery extends PageQuery {

    @Size(max = 32, message = "用户名筛选长度不能超过32个字符")
    private String username;
    @Size(max = 32, message = "昵称筛选长度不能超过32个字符")
    private String nickname;
    private UserStatus status;

    public void setUsername(String username) {
        this.username = !StringUtils.hasText(username) ? null : username.strip();
    }

    public void setNickname(String nickname) {
        this.nickname = !StringUtils.hasText(nickname) ? null : nickname.strip();
    }
}
